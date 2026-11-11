"""What every sandbox runtime shares (contract A), in three parts: the runtime framework (its
executable and the launch: `runtime_cli`, `launch`; a runtime gives its `Runtime`, `images`,
`caches`, `check`), the network filter (`egress`), and the relay to the host (`relay`)."""
