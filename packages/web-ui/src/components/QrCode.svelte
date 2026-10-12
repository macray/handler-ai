<script lang="ts">
  // A QR code as plain SVG shapes (no markup injected): black modules on a white quiet zone, so
  // phones read it in dark mode too.
  import qrcode from "qrcode-generator";

  let { text, size = 240 }: { text: string; size?: number } = $props();

  const code = $derived.by(() => {
    const qr = qrcode(0, "M");
    qr.addData(text, "Byte");
    qr.make();
    const n = qr.getModuleCount();
    let path = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) path += `M${c + 4} ${r + 4}h1v1h-1z`;
    return { n: n + 8, path };
  });
</script>

<svg width={size} height={size} viewBox="0 0 {code.n} {code.n}" shape-rendering="crispEdges" role="img" aria-label="pairing QR code" data-testid="qr">
  <rect width={code.n} height={code.n} fill="#fff" />
  <path d={code.path} fill="#000" />
</svg>
