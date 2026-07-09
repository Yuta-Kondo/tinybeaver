import { useState } from "react";
import type { MessageAttachment } from "../lib/attachments";
import { fileIcon } from "../lib/attachments";
import Icon from "./Icon";

type Viewer =
  | { mode: "image"; src: string; name: string }
  | { mode: "text"; name: string; text: string };

interface Props {
  attachments: MessageAttachment[];
}

export default function MessageAttachments({ attachments }: Props) {
  const [viewer, setViewer] = useState<Viewer | null>(null);

  if (!attachments.length) return null;

  function open(att: MessageAttachment) {
    if (att.thumb && (att.kind === "image" || att.kind === "pdf")) {
      setViewer({ mode: "image", src: att.thumb, name: att.name });
    } else if (att.text) {
      setViewer({ mode: "text", name: att.name, text: att.text });
    }
  }

  return (
    <>
      <div className="message-attachments">
        {attachments.map((att, i) => (
          <button
            key={`${att.name}-${i}`}
            type="button"
            className={`message-attachment${att.thumb ? " message-attachment--thumb" : ""}`}
            onClick={() => open(att)}
            title={`View ${att.name}`}
          >
            {att.thumb ? (
              <img src={att.thumb} alt="" className="message-attachment-thumb" />
            ) : (
              <span className="message-attachment-icon">{fileIcon(att.name)}</span>
            )}
            <span className="message-attachment-name">{att.name}</span>
          </button>
        ))}
      </div>

      {viewer?.mode === "image" && (
        <div className="lightbox-backdrop" onClick={() => setViewer(null)}>
          <img src={viewer.src} alt={viewer.name} className="lightbox-img" />
          <button className="lightbox-close" onClick={() => setViewer(null)} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
      )}

      {viewer?.mode === "text" && (
        <div className="attachment-modal-backdrop" onClick={() => setViewer(null)}>
          <div className="attachment-modal" onClick={(e) => e.stopPropagation()}>
            <div className="attachment-modal-header">
              <span className="attachment-modal-title">{viewer.name}</span>
              <button className="attachment-modal-close" onClick={() => setViewer(null)} aria-label="Close">
                <Icon name="close" size={14} />
              </button>
            </div>
            <pre className="attachment-modal-body">{viewer.text}</pre>
          </div>
        </div>
      )}
    </>
  );
}
