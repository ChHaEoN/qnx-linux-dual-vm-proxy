# ADR-003 — 硬體計時的 QNX Hypervisor 數字能從哪裡來？

**Status: Proposed — decision pending.** 本文的事實部分由 2026-09-09 的研究 workflow
產出（三個獨立 sweep，各附一個 skeptic 逐條重抓來源核對；被推翻的項目已剔除）。
它是決策的**輸入**，不是決策：選項的取捨、預算與授權問題由專案擁有者決定。
相關脈絡：[ADR-002](phase2-topology-decision.md)、[digital-twin-design.md §1a](digital-twin-design.md)、
[findings.md 2026-09-09](findings.md)、[orin-port.md 的 Sweep B 節](orin-port.md)、
[bsp-selection.md F7](bsp-selection.md)。本板 EL2/UEFI 開機證據：
[orin-l4t-boot-el2-uefi-evidence.txt](../logs/sample-boot/orin-l4t-boot-el2-uefi-evidence.txt)。

---

> 本文只整理經 skeptic 複核後**存活或被削弱**的事實；被推翻的項目已剔除並在文末列明。每條事實附引用鍵 `[x#]`，URL 列於各節末。研究日期 2026-09-09。

## 1. 問題陳述

本專案的 QNX Hypervisor (QHV) leg 目前只在 QEMU TCG（模擬 EL2）下跑，Windows 與 Orin Nano 兩個 host 都一樣（findings.md 2026-09-09 條目），所以 `qvm` 的 guest entry/exit、中斷注入等數字全是模擬器時間，不是矽時間。問題是：一個持 QNX Everywhere 個人授權、手上有 Jetson Orin Nano Dev Kit 與一個 32-vCPU quota AWS 帳號的人，能從哪個平台取得**真實 EL2 上、QNX 自己的量測方法所承認**的 hypervisor 延遲數字。

## 2. 三個選項的事實表

### (A) AWS Marketplace QNX AMI on Graviton（含 metal？）

選項 A 實際上拆成兩個完全不同的東西。

| 面向 | A-OS：`QNX OS 8.0` AMI | A-QHV：`QNX Hypervisor 2.2` AMI |
|---|---|---|
| **已確立** | 上架名 `QNX OS 8.0`（prodview-fyhziqwvrksrw），最新版本 `QNX OS 8.0.5 AMI - b67`，Arm 64-bit [a1]。Release notes：AMI「contains the QNX OS 8.0 kernel image for the EC2 environment」，無 qvm / vdev / hypervisor 字樣 [a2][a3]。Root IFS 明文鎖定：「This root IFS should remain unaltered by the user」[a4]；7.1 版 Getting Started 更直白：「the IFS is not customizable」[a5]。軟體費 $0.43–1.06/h + EC2 費，無 free trial，不退款 [a1]。 | 上架名 `QNX Hypervisor 2.2`（prodview-cse7ii7pszrxa，Build 207 2024.06.19），**只支援 c6g.metal / m6g.metal / r6g.metal** 三種 metal，軟體費 $1.50/h [a6]；release notes 列出 qvm、qvm-check、vdev-virtio-{blk,console,entropy,net}、vdev-shmem、vdev-smmu 等 [a7]。三種型號都是 64 vCPU（Graviton2）[a8]。 |
| **未知** | 定價表 14 列只看到 10 列（c7g.xlarge…c8g.12xlarge），**「無 metal」僅指可見列**；8.0.5 notes 只列 family（c7g/m7g/r7g/r8g），family 內含 .metal size，無法排除 [a3]。AMI 開機方式（UEFI vs 其他）QNX 未說明；AWS 說 Graviton 預設 UEFI，libstartup.a 有 efi_entry_point.o 等物件——僅為推論 [a9][a10]。 | Everywhere 使用者能否完成訂閱：EULA 要求「valid Project License」才能用 Hypervisor AMI，但 NC 授權 v7 全文零次出現 "hypervisor"，Hypervisor 是否算 "licensed on a project basis" 無法判定 [a11][a12]。 |
| **成本** | c7g.xlarge 約 $0.45/h 軟體費 + EC2 | $1.50/h + c6g.metal $2.48/h（eu-central-1）≈ $4/h [a6][c8] |
| **工夫** | 低（EC2 標準流程） | 低——**如果** quota 與授權過關 |
| **風險** | 零 hypervisor 價值 | 32-vCPU quota 直接擋 64-vCPU launch；是 7.1 世代產品，不是本專案的 SDP 8.0 image |
| **能量什麼** | 不能量任何 hypervisor 數字：它是 Nitro 虛擬化下的 EL1 單一 QNX tenant。只能當 2026-06-10 兩軌決策裡的「第三個 runtime substrate」（Track B），且當時的「unknown AMI software fee」現在已知且非零 | 真 EL2 上的 QNX 官方 qvm host——這正是要的東西，但是 Hypervisor 2.2 / SDP 7.1 世代 |
| **不能量什麼** | EL2 / VHE / guest exit | 與本專案 8.0 image 的同源比較 |
| **第一道便宜閘門** | 無須做；已可判死（作為 hypervisor 數字來源） | (1) 在 AWS Marketplace console 搜尋是否已出現 `QNX Hypervisor 8.0` listing（唯讀）；(2) 向 QNX 詢問 NC 授權下 Hypervisor AMI 的 Project License 適用性；(3) 若兩者皆通，提 L-1216C47A quota 升到 64（申請免費）[c9] |

**A 的補充事實（存活）：**
- Hypervisor 8.0.5 release notes（edition 2026-08-21）新增支援平台「AWS Graviton2, Graviton3」，並稱「This release enables support for 64-core Graviton 3 AMIs」[a13]。QNX 顯然在做 8.0 世代 Graviton3 hypervisor image，**但找不到任何 Marketplace listing**；notes 全文從未出現 "metal"。
- 8.0 GA / 8.0.4 notes 的支援平台為 NXP i.MX8QM、AWS Graviton2、Intel Raptor Lake，其他板子「contact your QNX representative」[a14]。
- QNX 官方 blog 明說 Hypervisor 8.0 已納入免費 QNX Everywhere 授權 [a15]；授權矩陣列 AWS 為 Hypervisor 8.0 的 Authorized Cloud Service Provider，且 NC/Academic 授權適用 [a12]。
- 本機 Software Center catalog（cache 為 8.0.4 世代，hypervisor.group 3.1.0 Build 18 可用；早於 8.0.5）中存在 8.0 世代 Graviton 工具：`com.qnx.qnx800.host.common.fvsp.image_builder`（「Platform tooling to build QEMU and Graviton images」，FVSP Early Access，experimental，本帳號 unavailable）——這是 7.1 `cabin.AWS_Graviton2` patchset 的 8.0 後繼 [a16]。**沒有** 8.0 Graviton BSP 或 hypervisor-host 板級套件 [a17]。
- Arm 上的 nested virtualization 在 AWS 仍是 metal-only：2026-02 / 2026-06 的 nested-virt 公告只涵蓋 Intel C8i/M8i/R8i 等 [a18][a19]。
- a1.metal（Graviton1，Cortex-A72，16 vCPU）是唯一在 32-vCPU quota 內的 Graviton metal；AWS 現行 price feed 無 a1，eu-central-1 $0.466/h 僅一個二手來源（aws-pricing.com），us-east-1 $0.408 [c8][c10]。它給 KVM 真 EL2（repo 2026-07-29 已實證），但**沒有可跑的 QNX host image**——除非 Hypervisor 2.2 AMI 能用，否則 a1.metal 量的是 KVM 而非 QHV。
- c7g.metal（Neoverse V1）有 FEAT_NV2（TRM ID_AA64MMFR2_EL1.NV = 0x2）[c11]，上游 `kvm-arm.mode=nested` 標為 experimental [c12]——即使 quota 放行，nested QHV 也是 trapped-EL2 數字，且需 kernel 支援；「會繼承 GICv3/NISV 問題」僅為假設。

URL：[a1] https://aws.amazon.com/marketplace/pp/prodview-fyhziqwvrksrw · [a2] https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qnxami_prod_release_notes/qnxcloud_sdp8_ami_rn.html · [a3] https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qnxami_prod_release_notes/qnxcloud_sdp805_ami_pu_rn.html · [a4] https://www.qnx.com/developers/docs/8.0/com.qnx.doc.qnxcloud.ami/topic/customize_qnx_amis.html · [a5] https://support7.qnx.com/download/download/70060/Getting_Started_with_QNX_in_the_Cloud_20230217.pdf · [a6] https://aws.amazon.com/marketplace/pp/prodview-cse7ii7pszrxa · [a7] https://www.qnx.com/developers/articles/rel_7110_1.html · [a8] https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html · [a9] https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ami-boot.html · [a10] `C:\Users\andy8\qnx800\target\qnx\aarch64le\usr\lib\libstartup.a`（`ntoaarch64-ar t`）· [a11] https://d7umqicpi7263.cloudfront.net/eula/aALIu1_JwXKqKd7c9HrZBHv-Hl5IqdSjyj4T321iJZU · [a12] https://www.qnx.com/legal/licensing/document_archive/current_matrix.pdf · [a13] https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/qh8.0_prod_release_notes/hypervisor8.0.5_rn.html · [a14] https://www.qnx.com/developers/docs/relnotes8.0/com.qnx.doc.release_notes/topic/hypervisor8.0_rn.html · [a15] https://qnx.software/en/blog/2026/free-access-to-qnx-hypervisor-with-qnx-everywhere · [a16] `C:\Users\andy8\.qnx\swupdate\cache\metadata\.packages\metadata\com.qnx.qnx800.host.common.fvsp.image_builder.__unavail__85359` · [a17] https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.nav/topic/about.html · [a18] https://aws.amazon.com/about-aws/whats-new/2026/02/amazon-ec2-nested-virtualization-on-virtual · [a19] https://aws.amazon.com/about-aws/whats-new/2026/06/nested-virtualization-intel-us-gov-cloud/

### (B) Native QNX port to Orin Nano（Tegra234）

| 面向 | 內容 |
|---|---|
| **已確立** | 開機鏈 BootROM → MB1 → MB2 → UEFI (edk2-nvidia) → L4TLauncher → kernel；可用 grub-install 換掉 BOOTAA64.efi，即任意 AArch64 EFI application 可當 OS loader [b1]。TF-A 把 BL33 交到「highest available Exception Level (EL2 if available)」[b2]，公開 AGX Orin dmesg 顯示 `All CPU(s) started at EL2` / `VHE mode initialized`。Tegra234 register map 公開於上游 DT：GICD 0x0f400000、GICR 0x0f440000（單一 2 MiB region，無 ITS node）、PSCI smc、uarta 0x03100000 / uarte 0x03140000（8250 類）、uarti 0x031d0000（sbsa-uart）、`serial0 = &tcu`（HSP mailbox，無 MMIO UART）[b3]。NVIDIA staff 對重用 TCU 為普通 UART：「we don't suggest and support for this use case」[b4]。SDP 8.0 install 實際出貨 `aarch64le/boot/sys/uefi.boot`、`mkifsf_uefi.exe`、libstartup.a 246 members 含 efi_entry_point.o、uefi*.o、acpi*.o、cpuid_a78ae.o（MIDR 0x4100D420）、callout_debug_tegra.o、callout_interrupt_t18x_* [a10]；hypervisor-guest BSP zip 附 Apache-2.0 源碼，唯一板目錄是 armv8_fm [b5]。本 session 以 `[virtual=aarch64le,uefi]` 跑 mkifs 產出 MZ/PE/0xAA64 的 AArch64 PE32+（文件卻說 uefi.boot 僅 x86_64）[b6]。edk2-nvidia 源碼樹 `SocT23X.conf` 有 `imply SOC_GENERAL`，`BuildGeneral.conf` `imply ACPI` / `imply DEVICETREE` [b7]。NVIDIA 三次明說不支援：2020「no plan to do」、2024「We don't support QNX on Jetson. It's only available on DRIVE platforms」、2025「There is no plan to support QNX OS on Jetson」[b8][b9][b10]。DRIVE AGX SDK program 為邀請制 [b11]。Catalog 有「QSC - Partner - NVIDIA Customers」資料夾內的 Orin 驅動套件（`com.qnx.qnx800.target.pci.hw.nvidia` T19x/T23x 等），但**無 NVIDIA BSP / startup** [a16]。授權：NC QDL v7 4.1(iii) 授權「modify the Software supplied as Source Code」用於任何 Non-Commercial Target System，無硬體清單限制 [b12]。 |
| **未知** | 本板（Orin Nano 而非 AGX Orin）EL2 交接**沒有留存 dmesg**——`logs/` 下無 `started at EL2` / `VHE mode initialized`，只有 orin-port.md 一個打勾句子；違反 repo「test before claim」。ACPI/shell「預設開啟」是源碼 `imply` 預設，**不是** NVIDIA 出貨韌體的證據；R36.4.3 Orin UEFI 頁無 ACPI 字樣 [b1][b7]。mkifs 產出的 PE entry 是否真的到達 efi_entry_point（armv8_fm/main.c 從不呼叫 is_uefi_boot()）。40-pin header 上是否有 CPU 可驅動的 8250 UART。t18x（Parker）PCIe/MSI callout 是否適用 Tegra234。tegra234-sdhci / PCIe 沒有已知 QNX driver。Tegra234 TRM 登入閘（HTTP 403）。 |
| **成本** | 硬體 $0（已擁有）；時間為主要成本 |
| **工夫** | 數週的無支援 BSP 工作：新 board directory、debug callout、timer/GIC/PSCI 初始化、storage driver；最終為 Experimental Software，無 vendor 路徑 |
| **風險** | (1) console：唯一 console 是 SPE 擁有的 TCU；(2) 三次 NVIDIA no-QNX 聲明；(3) 授權 4.6(c) 禁止 disassembly（2026-07-28 root cause 曾反組譯 startup-qemu-virt；2026-09-08 的 Apache-2.0 gic_v3.c 路徑才是乾淨立足點）、4.6(i) 禁止未經 BlackBerry 書面同意發布「performance or functional evaluation」結果——這是研究員的法律解讀，非 BlackBerry 聲明，但**讀在本 repo 每個已發布延遲數字上**，需 Architect/Docs 決定 [b12]；(4) Apache 標頭的源碼裝在 QDL 授權的 zip 裡，何者為準未定 |
| **能量什麼** | 若成功：A78AE 上真 VHE (el2-host) 的 QHV 數字，與 TCG leg 拓撲一致；同時是最強的 BSP-porting 敘事 |
| **不能量什麼** | 短期內任何東西；也不是 vendor 支援的組態 |
| **第一道便宜閘門** | 零成本、一小時內：(1) 在 Orin Nano 擷取並存入 `logs/` 的 dmesg（`started at EL2`、`VHE mode`、`EFI v2.x by EDK II`）；(2) 把本 session 的 UEFI PE 放到 ESP 當 BOOTAA64.efi，看 UEFI 是否至少載入它（任何 serial/TCU 輸出即算通過——但 TCU 輸出仍靠 L4T 韌體側）；(3) 用 `-cpu cortex-a72` / `-cpu max` 在 QEMU 複現 PAUTH abort，釐清 guest 到底需不需要 PAUTH（見 C） |

URL：[b1] https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/SD/Bootloader/UEFI.html · [b2] https://trustedfirmware-a.readthedocs.io/en/latest/design/firmware-design.html · [b3] https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/nvidia/tegra234.dtsi · [b4] https://forums.developer.nvidia.com/t/287340 · [b5] `bsp/BSP_hyp-guest-arm_be-800_SVN1018940_JBN323.zip`（lib/efi_entry_point.c、boards/armv8_fm/main.c）· [b6] https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html · [b7] https://github.com/NVIDIA/edk2-nvidia/blob/main/Platform/NVIDIA/KconfigIncludes/BuildGeneral.conf（及同目錄 SocT23X.conf）· [b8] https://forums.developer.nvidia.com/t/144240 · [b9] https://forums.developer.nvidia.com/t/284463 · [b10] https://forums.developer.nvidia.com/t/is-it-possible-to-port-qnx-os-to-nvidia-jetson-orin/339232 · [b11] https://developer.nvidia.com/drive/agx-sdk-program · [b12] https://www.qnx.com/download/download/51624/BB_QNX_Development_License_Non-Commercial_License_Class_v7_2025-12-10.pdf

### (C) 其他平台

| 平台 | 已確立 | 未知 | 成本 | 能量 / 不能量 | 第一道閘門 |
|---|---|---|---|---|---|
| **Raspberry Pi 4B** | QNX 自己的 getting-started repo（2025-12-01）：「The QNX Everywhere license ... includes an entitlement to QNX Hypervisor 8.0」；「the QNX-supplied Pi 4 BSP does not include a hypervisor build file variant」；build file 用 `startup-bcm2711-rpi4 ... -Q enable,el1-host`；README：「we are running the hypervisor host in EL1 (non-VHE) ... there are limitations with the VHE-enabled subsystems on the Pi 4」[c1]。`-Q enable,el1-host` 語意見 startup 文件 [c2]。**不在** QHV 8.0 支援平台清單，Pi 4 BSP notes 無 hypervisor 字樣——是 QNX 撰寫的 community recipe，不是 supported platform [a14][c3]。社群 EhabMagdyy/QNX-Hypervisor 在 Pi 4B 跑到 guest banner [c4]。價格 4 GB $60 / 8 GB $85（list，1 GB 版 BSP 不支援）[c5] | hypervisor 本體在 el1-host 下仍佔 EL2 為架構推論，非 QNX 聲明。本專案 guest 在 QEMU cortex-a57 上 abort `PE does not support PAUTH feature`（repo 把它歸因為 startup-armv8_fm 需 PAUTH，本身是推論），而社群在無 PAUTH 的 A72 上開得起來——兩邊都未驗證是否同一 image | ~$60–190（reseller 現價偏高） | **能**：真硬體 EL2 上 QNX 官方 qvm、QNX 承認的 trace 數字。**不能**：VHE / el2-host 拓撲（A72 為 ARMv8.0，無 VHE），與 TCG leg 不是同拓撲 | 買板前先在 QEMU `-cpu cortex-a72` 解 PAUTH 矛盾；買板後照 QNX recipe 跑 qvm-check + guest banner |
| **Raspberry Pi 5** | 有 8.0 BSP（`bsp.hw.raspberrypi_bcm2712_rpi5`，build 381，2026-01-15）；Cortex-A76 具 VHE；$70/95/145 [c5][c6] | **無任何** QNX 文件說 QHV 跑在 Pi 5（press release 提 Pi 5 是指 packages/self-hosting，非 hypervisor）[c7] | $70–145 | 若成功：el2-host VHE 拓撲，最接近 TCG leg；純實驗 | 拿 Pi 4 recipe 改 `-Q enable,el2-host` 試 |
| **NXP i.MX 8QuadMax MEK** | QHV 8.0 官方支援清單唯一可買的板 [a14]；$1,206.35，Pending Stock；8.0 BSP build 489（2026-01-28）notes 無 hypervisor 字樣 [c3] | Everywhere 可見的 BSP 是否含 `*-hypervisor.build` 變體（QNX 文件：「QNX provides some BSPs that contain a hypervisor variant of the buildfile」，未列舉是哪些）[c13] | ~$1,200 + 缺貨 | vendor 支援的 A53/A72 QHV 數字（仍非 VHE） | 先問 QNX / 看 BSP 內容再考慮 |
| **x86-64 QHV on Intel nested-virt EC2** | Raptor Lake 為支援平台 [a14]；`bsp.hw.x86_64` 本帳號可裝 [a16]；AWS C8i/M8i/R8i 提供 nested virt（2026-02）[a18] | QNX 未列此組態為支援；trapped-EL2 等價的 VMX nested | 一般 EC2 費 | 硬體輔助虛擬化數字，**但換 ISA**，放棄 aarch64 twin 前提 | 只當 trade 討論，不當 fix |
| **Graviton3 metal + nested KVM** | c7g.metal 64 vCPU $2.6384/h（eu-central-1，AWS feed 2026-09-09）[c8]；V1 具 FEAT_NV2 [c11]；upstream nested 模式 experimental [c12] | kernel 是否出貨此模式；QNX host image 從哪來 | quota 升 64 + ~$2.6/h | trapped-EL2 而非原生 | 同 A-QHV 閘門 |

**量測儀器（存活，頁面歸屬已修正）：** QNX 承認的方法是 `qvm` process 的 kernel trace（tracelogger / System Profiler）。「Most qvm trace events are Class 10 events」，ID 0 Guest Entry、1 Guest Exit、2 Create vCPU Thread、3/4 Assert/De-assert Interrupt、5/6 Virtual Timer、7 Guest Clock Cycles；「The timestamp for the ID 0 event should not be used to calculate the time spent in the guest」；% time in guest = time in guest / vCPU thread 總 RUNNING 時間（trace_events.html）[c14]。`clockcycles_offset`「is set during qvm startup and never changes」（tsc.html）[c15]。方法論：top-down 比較 native (N) vs VM (V) 同一 benchmark，bottom-up「record every hypervisor event over a specific time interval」（overhead.html）[c16]；hypervisor→guest→hypervisor round-trip「three to ten microseconds, depending on the SoC」（guest_exits.html）[c17]；「when a hardware device asserts an interrupt for a guest, the hypervisor must always intervene」（irqs.html）[c18]。Host trace 看不到 guest 內部。

URL：[c1] https://gitlab.com/qnx/hypervisor/getting-started · [c2] https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/s/startup_options.html · [c3] BSP 8.0 release notes（Pi 4 build 484、Pi 5 build 381、i.MX8QM MEK build 489），https://www.qnx.com/developers/docs/BSP8.0/ · [c4] https://github.com/EhabMagdyy/QNX-Hypervisor · [c5] https://www.raspberrypi.com/news/（2025-12-01 價格公告）· [c6] https://www.raspberrypi.com/products/raspberry-pi-5/ · [c7] https://qnx.software/en/press-release/2026/qnx-everywhere-expands-global-developer-ecosystem-through-education-innovation-and-open-collaboration · [c8] AWS on-demand price feed（b0.p.awsstatic.com，EU Frankfurt，Linux，2026-09-09）· [c9] https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html（L-1216C47A）· [c10] https://aws-pricing.com/a1.metal.html · [c11] Arm Neoverse V1 TRM 101427_0102_07（ID_AA64MMFR2_EL1.NV）· [c12] https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html（`kvm-arm.mode=nested`）· [c13] https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/config/build_methods.html · [c14] https://www.qnx.com/developers/docs/8.0/com.qnx.doc.hypervisor.user/topic/debug/trace_events.html · [c15] …/topic/debug/tsc.html · [c16] …/topic/perform/overhead.html · [c17] …/topic/perform/guest_exits.html · [c18] …/topic/perform/irqs.html

## 3. 對量測目標的意義

**能產出 QNX 承認的 hypervisor 延遲數字（真 EL2 + 官方 qvm + Class 10 trace）的選項，依可及性排序：**

1. **Pi 4B（C）**——唯一有 QNX 自撰 recipe、Everywhere 授權明示涵蓋、$60–85 的路徑。代價：el1-host 非 VHE，與本專案 TCG leg 的 el2-host 拓撲不同，所以得到的是「QHV 在硬體 EL2 的絕對數字」而非「TCG leg 的矽版對照」。
2. **Pi 5（C）**——可能給 VHE 拓撲，但零文件，純實驗。
3. **AWS Graviton metal + QNX host image（A-QHV）**——vendor 自己的雲端 hypervisor 路徑；被 quota、7.1 世代、Project License 三重擋住。**若** Hypervisor 8.0.5 的 Graviton3 AMI 上架，這會變成最貼近本專案 8.0 image 的一條——目前是 watch item，不是計畫。
4. **i.MX8QM MEK（C）**——唯一 vendor 支援且可買，$1,200 且缺貨，BSP hypervisor 變體未證實。
5. **Orin Nano native（B）**——理論上最好（A78AE + VHE，與 TCG leg 同拓撲、同 host），實際上是數週無支援 BSP 工作。

**A-OS AMI 與 a1.metal 都不在此清單**：前者是 EL1 tenant、鎖 IFS；後者沒有 QNX host image 可跑（只能量 KVM）。

**模擬 leg 仍能貢獻的：** (i) 量測儀器本身——Class 10 trace 的擷取腳本、ID 7 + clockcycles_offset 的換算、guest-exit 計數、N-vs-V 流程，現在就能在 TCG 上開發並驗證**形狀**，換平台後只換時間軸；(ii) exit 種類與次數的分佈（哪些 MMIO / sysreg 觸發 exit）在 TCG 與矽上應近似，可作 sanity 比對；(iii) host-only twin diff（Windows vs Orin 同 QEMU 版本）繼續是乾淨的一變數比較；(iv) 任何硬體數字都需要 TCG 版作為「這裡是模擬 vs 這裡是矽」的對照欄。

## 4. 建議

**建議：先花零元把三個未知打掉，再用 Pi 4B（≤$100）取得第一個硬體 EL2 的 QHV 數字；AWS 只在 Hypervisor 8.0 Graviton listing 出現且授權問題有答案時才動；Orin native 保留為敘事與長期項目，不作為量測路徑。**

理由：
- 任何 AWS 路徑到真 EL2 都要過 64-vCPU quota（a1.metal 除外，但它沒有 QNX host image）；A-QHV 還是 7.1 世代與未解的 Project License 閘門——三個未知疊在 $4/h 上，不值得先花。
- Pi 4B 是唯一「QNX 自己寫了 recipe + 授權明示 + 兩位數美元」的組合；el1-host 的拓撲差異要在 ADR 裡誠實標示，但它給的是 QNX 承認的儀器在真矽上的第一個讀數，這是目前完全沒有的東西。
- Orin native 的每個環節（UEFI EL2 交接、AArch64 UEFI startup 源碼、mkifs 出 PE、授權允許改源碼）都通，但工程量與 console 問題讓它成為「數週的 BSP porting 作品集項目」，不是「幾天內拿到數字」。
- 8.0.5 notes 的「64-core Graviton 3 AMIs」是最值得盯的訊號，但當前無 listing，且 64-core 暗示 metal-class，仍撞 quota。

**花錢或花週之前必須解掉的未知（明列）：**
1. **PAUTH 矛盾**：本專案 guest 在 QEMU cortex-a57 的 `PE does not support PAUTH feature` vs 社群在 A72 Pi 4B 開機成功——在 QEMU `-cpu cortex-a72` / `-cpu max,pauth=off` 複現，決定 Pi 4 是否要另建 guest。
2. **Orin Nano 本板 EL2 證據**：擷取 dmesg 存入 `logs/`（現在只有一個打勾句）。
3. **Software Center refresh**：cache 是 8.0.4 世代；確認 Hypervisor 8.0.5 group 是否對 Everywhere 帳號開放、有無任何 Graviton/AWS 套件、`fvsp.image_builder` 是否仍 unavailable。
4. **`QNX Hypervisor 8.0` Marketplace listing 是否存在**（console 內唯讀搜尋；本次只能靠搜尋引擎與 JS-rendered 空頁）。
5. **NC 授權下 Hypervisor AMI 的 Project License 適用性**（問 QNX；NC v7 零次提 hypervisor）。
6. **NC v7 4.6(i)**（不得未經書面同意發布 performance evaluation 結果）與 **4.6(c)**（不得反組譯）對本 repo 已發布數字與 2026-07-28 反組譯的暴露——Architect/Docs/Cyber 決定，非研究可解。
7. **Pi 4 BSP 是否已加入 hypervisor variant**（getting-started 說「At this time」沒有）及 **i.MX8QM MEK BSP 的 hypervisor variant 狀態**。
8. **Pi 5 el2-host 是否可行**（無文件；買板前不知）。
9. **QNX OS 8.0 AMI 定價表未見的 4 列**是否含 .metal——只有在考慮 A-OS 當 substrate 時才重要。

## 5. 沒查到的事（三次 sweep 合併、去重）

**AWS / QNX 雲端**
- `QNX OS 8.0` listing 的完整 14 列 instance 表（只見 10 列；m7g/r7g/r8g 列未見）。
- 任何 `QNX Hypervisor 8.0 / 8.0.5` 的 AWS Marketplace listing（搜尋引擎、seller profile、Marketplace 搜尋頁皆無；後兩者 JS-rendered 空白；AWS API 不在範圍內）。絕對證據缺席。
- QNX 對 AMI 開機方式（UEFI 與否）與所用 startup / BSP 的任何說明；「QNX Software in the Cloud」下載群（programid=74127）與 Hypervisor 8.0.5 下載群（programid=78876）皆轉登入頁。
- QNX 任何說 Graviton hypervisor target 是 `*.metal` 的文字（"metal" 從未出現；由 Hypervisor 2.2 listing 與 AWS nested-virt 政策推得）。
- 8.0 世代 Graviton BSP 或 hypervisor-host 套件（cache 早於 8.0.5，需 refresh 才能定論）。
- QNX Hypervisor 是否對 Non-Commercial 使用者屬「licensed on a project basis」（Product Portfolio Guide 需登入）。
- 7.1「Installing and running QNX Cabin for Cloud」技術文（addon_hypervisor_ami.html 404，僅搜尋摘要）。
- QNX listings 支援的 AWS regions。
- AWS re:Post Graviton nested-virt 討論串（HTTP 403）。
- Everywhere 帳號能否實際完成 Hypervisor 2.2 listing 訂閱（需執行訂閱動作，超出範圍）。
- a1 family 在 AWS 現行 price feed 的價格（eu-central-1 $0.466 僅 aws-pricing.com 一個二手來源；vantage 只顯示 $0.408 us-east-1）。
- QNX 8.0 BSP 公開目錄裡任何 AWS/Graviton 條目；QNX OS 8.0 AMI notes 裡任何 hypervisor 提及。

**Orin / Tegra234**
- NVIDIA 對 Orin Nano（非 AGX Orin）UEFI 是否有 ACPI / "O/S Hardware Description Selection" 切換的說明；出貨韌體是否啟用 ACPI / UEFI shell（只有源碼 `imply` 預設）。
- 本板 Orin Nano 的 EL2 交接 dmesg（`logs/` 下沒有）。
- 任何 QNX 移植到任何 Jetson 世代（TX1/TX2/Xavier/Orin）的紀錄，官方或社群。
- 任何可用的 seL4 / Xen / Zephyr / FreeBSD Orin 移植。
- QNX 8.0 文件中的 AArch64 UEFI startup（文件說 uefi.boot 僅 x86_64，與 install 內容矛盾）。
- Tegra234 TRM 內容（HTTP 403，登入閘）。
- Orin Nano 40-pin header 上是否有 CPU 可驅動的 8250 UART；uartc@c280000 能否從 SPE 接管（「backed by uartc@c280000」與「TCU muxing runs in the SPE」細節未在抓到的討論串中看到，未驗證）。
- callout_interrupt_t18x_* 是否適用 Tegra234 PCIe/MSI。
- UEFI spec 2.10/2.11 §2.3.6 原文（uefi.org 403）。
- 需實跑才能確認：mkifsf_uefi AArch64 image 的 PE entry 是否到達 efi_entry_point；任何以 armv8_fm 為底的 Tegra234 startup 是否能開機；有 board startup 後 QHV host（qvm + EL2 procnto）能否原生執行。
- grub `--target=arm64-efi` 不在 NVIDIA 頁面上（頁面為 `grub-install --bootloader-id=Ubuntu`）。

**其他平台 / 儀器**
- 任何 QNX 說 QHV 8.0 跑在 Raspberry Pi 5 的聲明。
- 哪些 SDP 8.0 board BSP 附 `*-hypervisor.build` 變體的公開清單（i.MX8QM 例子只在搜尋摘要）。
- `qvm-check` 工具的文件。
- QNX Hypervisor Benchmarking white paper 內容（登記閘）。
- QHV 8.0 `qvm` 參考頁裡任何統計 / 監控選項（負向主張未再核）。
- Toradex Apalis iMX8QM + Ixora 現價（只有 2018 數字）。
- QNX blog 的發布日期（以 2026-01-06 press release 代替；但 README 的 entitlement 句早在 2025-12-01 即存在）。
- 本專案的 hypervisor_guest_arm guest 在真 A72 Pi 4 上能否開機（需硬體）。
- QNX Everywhere 的 EULA 本文（entitlement 主張只來自 blog / press / README，均 QNX 撰寫但非授權文件）。

**已剔除的推翻項目（不採用）：** 「catalog 無任何 com.qnx.qnx800 Graviton 套件」（有 fvsp.image_builder）；「catalog 無 NVIDIA」（有 partner 資料夾驅動套件，無 BSP）；「SocT23X 是否滿足 TEGRA_ACPI 閘門未解」（已解：`imply SOC_GENERAL`）；DaneLLL 引言日期（應為 2025-10-20，thread 348348）；orin-native sweep 的「no other repo file was modified」（docs/bsp-selection.md 亦為 dirty）；「press release 只提 Pi 4B」（有提 Pi 5，但非 hypervisor 脈絡）；「vantage 亦給 $0.466」（僅 aws-pricing.com）。另已修正：Finding 3 引言的頁面歸屬；「officially documented path」降為「QNX-authored recipe, unsupported platform」；Pi 5 生產至 2036 出自產品頁而非新聞稿（本文未引用該句）。

**相關檔案（絕對路徑）：** `E:/Project/qnx-linux-dual-vm-proxy/docs/findings.md`（2026-06-10、2026-07-29、2026-09-09 條目）、`E:/Project/qnx-linux-dual-vm-proxy/docs/orin-port.md`（Research sweep B 段落，第 149–435 行，未提交）、`E:/Project/qnx-linux-dual-vm-proxy/docs/bsp-selection.md`（F7 段落，未提交）、`E:/Project/qnx-linux-dual-vm-proxy/logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log`、`E:/Project/qnx-linux-dual-vm-proxy/logs/sample-boot/orin-qhv-tcg-q62-a57-control.log`（第 49 行 PAUTH 字串）。本回覆未修改任何 repo 檔案。
