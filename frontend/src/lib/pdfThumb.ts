// Render the first page of a PDF to a small JPEG data URL for preview.
// pdf.js is loaded dynamically so it never bloats the main bundle, and any
// failure falls back to null (the caller then shows the generic file icon).

export async function renderPdfThumbnail(file: File, maxWidth = 1400): Promise<string | null> {
  try {
    // Legacy build avoids top-level await (compatible with the app's build target).
    const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
    // Vite bundles this worker as an asset via the URL constructor.
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
      import.meta.url
    ).href;

    const data = new Uint8Array(await file.arrayBuffer());
    const pdf = await pdfjs.getDocument({ data }).promise;
    const page = await pdf.getPage(1);

    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(2, maxWidth / base.width);
    const viewport = page.getViewport({ scale });

    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    await page.render({ canvasContext: ctx, viewport }).promise;
    const url = canvas.toDataURL("image/jpeg", 0.82);
    pdf.destroy();
    return url;
  } catch {
    return null;
  }
}
