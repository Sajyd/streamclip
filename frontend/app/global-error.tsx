"use client";

// Replaces the root layout when it fails itself: it must render the whole
// document and cannot rely on the application's styles or components.
export default function GlobalError({ retry }: { error: unknown; retry: () => void }) {
  return (
    <html lang="fr">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "1.5rem",
          textAlign: "center",
          background: "#07070b",
          color: "#f4f4f8",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <title>Une erreur est survenue · STREAMCLIP</title>
        <h1 style={{ fontSize: "1.5rem", margin: 0 }}>Une erreur est survenue</h1>
        <p style={{ margin: 0, color: "#a3a3b5" }}>La page n&apos;a pas pu être affichée.</p>
        <button
          type="button"
          onClick={() => retry()}
          style={{
            padding: "0.6rem 1.2rem",
            borderRadius: "0.6rem",
            border: 0,
            background: "#7c5cff",
            color: "#fff",
            fontSize: "0.95rem",
            cursor: "pointer",
          }}
        >
          Réessayer
        </button>
      </body>
    </html>
  );
}
