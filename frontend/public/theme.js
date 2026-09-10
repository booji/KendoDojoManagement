// Pre-paint theme resolution. Kept in public/ rather than inline in
// index.html because the production image serves that HTML under
// Content-Security-Policy: default-src 'self', which blocks inline
// scripts — an inline version runs under Vite and silently does nothing
// in production (#385). Vite copies public/ to the build root verbatim,
// so this stays a same-origin /theme.js in both.
//
// Must stay synchronous and above the app bundle: it runs before first
// paint so the page never flashes the wrong theme.
(function () {
  // The cookie is the server's copy of the preference (#324); on a client
  // whose localStorage has never seen this user it is the only source
  // available before first paint.
  var m = document.cookie.match(/(?:^|;\s*)theme=(light|dark|system)/);
  var saved = m ? m[1] : localStorage.getItem("theme") || "system";
  var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  if (saved === "dark" || (saved === "system" && prefersDark)) {
    document.documentElement.classList.add("dark");
  }
})();
