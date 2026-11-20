//! The svc client: one TCP connection per run to a monitor's service port, one request outstanding at a
//! time, as `kind4_client._roundtrip` and `_end_session` are.
//!
//! [`Link::roundtrip`] sends one 64-byte frame and reads exactly 64 bytes within the reply deadline; a
//! closed peer, a short read or the deadline is an error. [`Link::end_session`] shuts the write side and
//! takes any byte that arrives in the next 200 ms as an error (`trailing`). Nothing here keeps or prints a
//! time: the deadlines are bounds, not measurements.

use std::fmt;
use std::io::{self, ErrorKind, Read, Write};
use std::net::{Shutdown, TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

use crate::frame::{FRAME_TOTAL_BYTES, Frame};

/// `kind4_client._roundtrip`'s read deadline.
pub const DEFAULT_REPLY_TIMEOUT_MS: u64 = 3000;
/// `kind4_client._end_session`'s wait for trailing bytes.
pub const TRAILING_WAIT_MS: u64 = 200;
/// `kind4_client._connect`'s connect timeout.
pub const CONNECT_TIMEOUT_MS: u64 = 5000;

#[derive(Debug)]
pub enum LinkError {
    Resolve(String),
    Connect(io::Error),
    Send(io::Error),
    Recv(io::Error),
    /// The peer closed the connection after `got` of 64 reply bytes.
    Closed {
        got: usize,
    },
    /// The reply deadline passed after `got` of 64 reply bytes.
    Deadline {
        got: usize,
    },
    /// Bytes arrived after the session's last reply.
    Trailing {
        got: usize,
    },
    Shutdown(io::Error),
}

impl fmt::Display for LinkError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LinkError::Resolve(e) => write!(f, "cannot resolve the host: {e}"),
            LinkError::Connect(e) => write!(f, "connect: {e}"),
            LinkError::Send(e) => write!(f, "send: {e}"),
            LinkError::Recv(e) => write!(f, "recv: {e}"),
            LinkError::Closed { got } => {
                write!(
                    f,
                    "closed: the peer closed after {got} of {FRAME_TOTAL_BYTES} reply bytes"
                )
            }
            LinkError::Deadline { got } => {
                write!(
                    f,
                    "deadline: {got} of {FRAME_TOTAL_BYTES} reply bytes by the reply deadline"
                )
            }
            LinkError::Trailing { got } => {
                write!(f, "trailing: {got} byte(s) after the last reply")
            }
            LinkError::Shutdown(e) => write!(f, "shutdown: {e}"),
        }
    }
}

impl std::error::Error for LinkError {}

fn timed_out(e: &io::Error) -> bool {
    matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut)
}

/// One svc connection.
pub struct Link {
    stream: TcpStream,
    reply_timeout: Duration,
}

impl Link {
    /// Connect to `host:port` with TCP_NODELAY (each address in turn, as `socket.create_connection`).
    pub fn connect(host: &str, port: u16, reply_timeout: Duration) -> Result<Link, LinkError> {
        let addrs = (host, port)
            .to_socket_addrs()
            .map_err(|e| LinkError::Resolve(e.to_string()))?;
        let mut last = None;
        for addr in addrs {
            match TcpStream::connect_timeout(&addr, Duration::from_millis(CONNECT_TIMEOUT_MS)) {
                Ok(stream) => {
                    stream.set_nodelay(true).map_err(LinkError::Connect)?;
                    return Ok(Link {
                        stream,
                        reply_timeout,
                    });
                }
                Err(e) => last = Some(e),
            }
        }
        Err(match last {
            Some(e) => LinkError::Connect(e),
            None => LinkError::Resolve(format!("no address for {host}")),
        })
    }

    /// Send one frame and read exactly one 64-byte reply within the reply deadline.
    pub fn roundtrip(&mut self, frame: &Frame) -> Result<Frame, LinkError> {
        self.stream.write_all(frame).map_err(LinkError::Send)?;
        let deadline = Instant::now() + self.reply_timeout;
        let mut buf = [0u8; FRAME_TOTAL_BYTES];
        let mut got = 0;
        while got < FRAME_TOTAL_BYTES {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return Err(LinkError::Deadline { got });
            }
            self.stream
                .set_read_timeout(Some(left))
                .map_err(LinkError::Recv)?;
            match self.stream.read(&mut buf[got..]) {
                Ok(0) => return Err(LinkError::Closed { got }),
                Ok(n) => got += n,
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(e) if timed_out(&e) => return Err(LinkError::Deadline { got }),
                Err(e) => return Err(LinkError::Recv(e)),
            }
        }
        Ok(buf)
    }

    /// End the session: shut the write side, then any byte read within 200 ms is `Trailing`.
    pub fn end_session(self) -> Result<(), LinkError> {
        self.stream
            .shutdown(Shutdown::Write)
            .map_err(LinkError::Shutdown)?;
        self.stream
            .set_read_timeout(Some(Duration::from_millis(TRAILING_WAIT_MS)))
            .map_err(LinkError::Recv)?;
        let mut one = [0u8; 1];
        match (&self.stream).read(&mut one) {
            Ok(0) => Ok(()),
            Ok(n) => Err(LinkError::Trailing { got: n }),
            Err(e) if timed_out(&e) => Ok(()),
            Err(e) => Err(LinkError::Recv(e)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

    /// A one-connection peer on loopback that runs `serve` on the accepted stream.
    fn peer<F>(serve: F) -> (u16, thread::JoinHandle<()>)
    where
        F: FnOnce(TcpStream) + Send + 'static,
    {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        let h = thread::spawn(move || {
            let (s, _) = l.accept().unwrap();
            serve(s);
        });
        (port, h)
    }

    fn read_request(s: &mut TcpStream) -> Frame {
        let mut f = [0u8; FRAME_TOTAL_BYTES];
        s.read_exact(&mut f).unwrap();
        f
    }

    fn wait_eof(s: &mut TcpStream) {
        let mut b = [0u8; 1];
        let _ = s.read(&mut b);
    }

    fn connect(port: u16, ms: u64) -> Link {
        Link::connect("127.0.0.1", port, Duration::from_millis(ms)).unwrap()
    }

    fn frame(x: u8) -> Frame {
        [x; FRAME_TOTAL_BYTES]
    }

    #[test]
    fn a_reply_in_two_writes_is_read_whole() {
        let (port, h) = peer(|mut s| {
            let req = read_request(&mut s);
            s.write_all(&req[..10]).unwrap();
            thread::sleep(Duration::from_millis(50));
            s.write_all(&req[10..]).unwrap();
            wait_eof(&mut s);
        });
        let mut link = connect(port, 3000);
        assert_eq!(link.roundtrip(&frame(7)).unwrap(), frame(7));
        link.end_session().unwrap();
        h.join().unwrap();
    }

    #[test]
    fn a_peer_that_closes_mid_reply_is_an_error() {
        let (port, h) = peer(|mut s| {
            let req = read_request(&mut s);
            s.write_all(&req[..30]).unwrap();
        });
        let mut link = connect(port, 3000);
        assert!(matches!(
            link.roundtrip(&frame(1)),
            Err(LinkError::Closed { got: 30 })
        ));
        h.join().unwrap();
    }

    #[test]
    fn a_silent_peer_hits_the_deadline() {
        let (port, h) = peer(|mut s| {
            read_request(&mut s);
            wait_eof(&mut s);
        });
        let mut link = connect(port, 200);
        assert!(matches!(
            link.roundtrip(&frame(2)),
            Err(LinkError::Deadline { got: 0 })
        ));
        drop(link);
        h.join().unwrap();
    }

    #[test]
    fn bytes_after_the_last_reply_are_trailing() {
        let (port, h) = peer(|mut s| {
            let req = read_request(&mut s);
            s.write_all(&req).unwrap();
            s.write_all(&[0]).unwrap();
            wait_eof(&mut s);
        });
        let mut link = connect(port, 3000);
        assert_eq!(link.roundtrip(&frame(3)).unwrap(), frame(3));
        assert!(matches!(
            link.end_session(),
            Err(LinkError::Trailing { got: 1 })
        ));
        h.join().unwrap();
    }

    #[test]
    fn the_default_deadline_and_the_trailing_window() {
        assert_eq!((DEFAULT_REPLY_TIMEOUT_MS, TRAILING_WAIT_MS), (3000, 200));
    }

    #[test]
    fn a_clean_end_of_session() {
        let (port, h) = peer(|mut s| {
            for _ in 0..3 {
                let req = read_request(&mut s);
                s.write_all(&req).unwrap();
            }
            wait_eof(&mut s);
        });
        let mut link = connect(port, 3000);
        for x in 4..7 {
            assert_eq!(link.roundtrip(&frame(x)).unwrap(), frame(x));
        }
        link.end_session().unwrap();
        h.join().unwrap();
    }
}
