/**
 * The Content Security Policy (CSP) of the app's pages.
 *
 * A CSP tells the browser which scripts, styles and connections the page may
 * use. Everything the agent shows comes from an AI and from uploaded files, so
 * the UI renders it as text. The CSP is a second line of defense: even if a
 * bug ever let text become HTML, the browser would refuse to run any script
 * that doesn't carry this request's nonce, a random value that an attacker
 * can't guess.
 */

export function contentSecurityPolicy(nonce: string, isDevelopment: boolean): string {
  // React needs eval() in development only, for its debugging tools.
  const devScripts = isDevelopment ? " 'unsafe-eval'" : "";
  return [
    "default-src 'self'",
    // Only scripts with this request's nonce, and the scripts they load.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${devScripts}`,
    // Plotly adds <style> elements and style attributes while it draws.
    "style-src 'self' 'unsafe-inline'",
    // Plotly's "download as PNG" button makes a data: image.
    "img-src 'self' blob: data:",
    "font-src 'self'",
    // The page may only call its own server.
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    // No other site may show the app in a frame.
    "frame-ancestors 'none'",
  ].join("; ");
}
