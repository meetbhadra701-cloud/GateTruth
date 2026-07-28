# Secure execution

Scoring containers run without network access, Linux capabilities, elevated
privileges, or write access to the repository. The repository is staged from
`git archive`, so `.git/` is never present in the execution container. A
separate host directory is the only writable bind mount.

Prepare an immutable source snapshot and writable output directory:

```bash
mkdir -p build/secure-src build/secure-output/results
git archive --format=tar HEAD | tar -xf - -C build/secure-src
chmod -R a+rX build/secure-src
chmod -R 0777 build/secure-output
```

Use these flags for every scoring or test execution:

```text
--network none
--cap-drop=ALL
--security-opt no-new-privileges
--memory=4g
--pids-limit=512
--cpus=2
--mount type=bind,src=<snapshot>,dst=/work,readonly
--mount type=bind,src=<output>,dst=/output
```

Commands that update the spend ledger or generate derived results also mount
`<output>/results` at `/work/results`. This is still a separate writable output
tree; the source snapshot remains read-only.

For example:

```bash
docker run --rm \
  --network none \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --memory=4g \
  --pids-limit=512 \
  --cpus=2 \
  --mount "type=bind,src=$PWD/build/secure-src,dst=/work,readonly" \
  --mount "type=bind,src=$PWD/build/secure-output,dst=/output" \
  --workdir /work \
  siliconbench:v1 \
  ./siliconbench run \
    --task t1_gray_counter \
    --submission tasks/t1_gray_counter/ref/ref.sv \
    --out /output/t1_gray_counter.json
```

Provider generation is a separate networked host-side step. Never pass provider
API keys to a scoring container. Official hidden tests may be mounted read-only
for the trusted harness, but the harness removes their root path from the
untrusted simulation subprocess environment.
