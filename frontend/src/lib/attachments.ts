export type AttachmentKind = "image" | "pdf" | "file";

export interface MessageAttachment {
  name: string;
  kind: AttachmentKind;
  thumb?: string;
  text?: string;
}

const IMAGE_EXTS = new Set(["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "tiff", "tif"]);

export function attachmentKind(name: string): AttachmentKind {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_EXTS.has(ext)) return "image";
  if (ext === "pdf") return "pdf";
  return "file";
}

export function fileIcon(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "📄";
  if (ext === "csv" || ext === "xlsx" || ext === "xlsm") return "📊";
  if (["md", "txt"].includes(ext)) return "📝";
  if (ext === "json") return "{ }";
  return "📎";
}

export function filesToAttachments(
  files: { name: string; text: string; thumb?: string }[],
  images: string[] = [],
): MessageAttachment[] {
  const fromImages = images.map((thumb, i) => ({
    name: `image-${i + 1}.png`,
    kind: "image" as const,
    thumb,
  }));
  const fromFiles = files.map((f) => {
    const kind = attachmentKind(f.name);
    return {
      name: f.name,
      kind,
      thumb: f.thumb,
      text: kind === "file" || kind === "pdf" ? f.text : undefined,
    };
  });
  return [...fromImages, ...fromFiles];
}
