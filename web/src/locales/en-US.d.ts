// Ambient module declaration for the plain-JS EN locale bundle.
// Without this, vue-tsc errors with TS7016 (no declaration for en-US.js).
declare const enUSMessages: Record<string, any>
export default enUSMessages
