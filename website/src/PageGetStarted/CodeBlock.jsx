import { useState } from "react";

// Dark code block with a copy-to-clipboard button.
const CodeBlock = ({ code, label }) => {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be refused (insecure context); the text is still selectable.
    }
  };

  return (
    <div className="relative">
      {label && (
        <div className="font-lato text-xs uppercase tracking-wide text-stone-500 mb-1">{label}</div>
      )}
      <pre className="bg-brand-950 text-brand-100 font-mono text-xs md:text-sm rounded-lg p-4 overflow-x-auto">
        <code>{code}</code>
      </pre>
      <button
        onClick={copy}
        className="absolute top-1 right-2 text-xs font-lato px-2 py-1 rounded bg-brand-800 text-brand-100 hover:bg-brand-700"
        style={{ top: label ? "1.75rem" : "0.5rem" }}
        aria-label="Copy to clipboard"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
};

export default CodeBlock;
