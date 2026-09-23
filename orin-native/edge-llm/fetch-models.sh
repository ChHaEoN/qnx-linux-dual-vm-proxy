#!/usr/bin/env bash
#
# fetch-models.sh -- put the two vision-language models on the board, and refuse
# anything that does not hash as recorded.
#
# WEIGHTS NEVER ENTER THIS REPO. They are 0.4-2.5 GB each and .gitignore blocks
# *.gguf outright; what the repo carries is this manifest -- repository, file and
# sha256 -- which is the same shape results/qhv-images-SHA256SUMS.txt uses for
# the QNX images it also may not ship.
#
# LICENCES, CHECKED ON THE BASE MODEL, NOT THE GGUF REPOSITORY. Both models below
# are Apache-2.0 on the card of the model they were converted from. That check is
# not pedantry: Qwen2.5-VL-3B's GGUF repository advertises `apache-2.0` in its
# metadata while the base model card carries no licence field at all, so reading
# the GGUF repo alone would have imported an unknown licence into a public repo.
#
# Usage: fetch-models.sh [DIR]     (default ~/models)
set -eu
DIR="${1:-$HOME/models}"
mkdir -p "$DIR"
cd "$DIR"

# repo|file|sha256
MANIFEST='
Qwen/Qwen3-VL-4B-Instruct-GGUF|Qwen3VL-4B-Instruct-Q4_K_M.gguf|66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a
Qwen/Qwen3-VL-4B-Instruct-GGUF|mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf|30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d
ggml-org/SmolVLM-500M-Instruct-GGUF|SmolVLM-500M-Instruct-Q8_0.gguf|9d4612de6a42214499e301494a3ecc2be0abdd9de44e663bda63f1152fad1bf4
ggml-org/SmolVLM-500M-Instruct-GGUF|mmproj-SmolVLM-500M-Instruct-Q8_0.gguf|d1eb8b6b23979205fdf63703ed10f788131a3f812c7b1f72e0119d5d81295150
'

# A here-string, not `printf | while`: a pipeline puts the loop in a subshell,
# where rc=1 is set on a copy and thrown away, so a mismatching model would exit
# 0 and the caller would proceed with the wrong weights.
rc=0
while IFS='|' read -r repo file want; do
	[ -n "${file:-}" ] || continue
	if [ ! -s "$file" ]; then
		echo "fetching $file"
		curl -fsS -L -o "$file.part" "https://huggingface.co/$repo/resolve/main/$file"
		mv "$file.part" "$file"
	fi
	got="$(sha256sum "$file" | cut -d' ' -f1)"
	if [ "$got" = "$want" ]; then
		echo "ok   $file"
	else
		# Do not delete it: a mismatch may be a model the owner replaced on
		# purpose, and deleting several GB on a guess is worse than stopping.
		echo "HASH MISMATCH $file" >&2
		echo "  expected $want" >&2
		echo "  got      $got" >&2
		rc=1
	fi
done <<< "$MANIFEST"

exit "$rc"
