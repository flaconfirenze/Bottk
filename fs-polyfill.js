// This file is intentionally left empty.
// It acts as a polyfill for the Node.js 'fs' module, which is not
// available in the Cloudflare Workers runtime. By aliasing 'fs' to this
// empty file in wrangler.toml, we prevent build errors from packages
// that optionally try to import 'fs'.
export default {};
