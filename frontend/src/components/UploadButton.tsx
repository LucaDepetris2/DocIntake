import { useRef } from "react";
import { api } from "../api/client";
import { useAction } from "../lib/useApi";
import { ErrorText } from "./ui";

/** Upload one or more PDFs; calls `onDone` once all of them are accepted. */
export function UploadButton({ onDone }: { onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const upload = useAction(async (files: File[]) => {
    await Promise.all(files.map((f) => api.upload("/documents", f)));
    onDone();
  });

  return (
    <span>
      <input
        ref={input}
        type="file"
        accept="application/pdf"
        multiple
        hidden
        onChange={(e) => {
          void upload.run(Array.from(e.target.files ?? []));
          e.target.value = ""; // allow re-selecting the same file
        }}
      />
      <button className="primary" disabled={upload.busy} onClick={() => input.current?.click()}>
        {upload.busy ? "Uploading…" : "Upload PDFs"}
      </button>
      <ErrorText error={upload.error} />
    </span>
  );
}
