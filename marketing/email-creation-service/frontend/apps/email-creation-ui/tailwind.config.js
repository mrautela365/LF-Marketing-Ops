// Minimal Tailwind config for the email-creation-ui skeleton app.
// Mirrors the shape of lfx-self-serve's apps/lfx-one/tailwind.config.js
// (content globs + theme.extend) without the brand-specific token imports,
// which live in @lfx-one/shared and are out of scope for this skeleton pass.

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{html,ts}'],
  theme: {
    extend: {},
  },
  plugins: [],
};
