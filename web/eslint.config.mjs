import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // All UI text comes from the message catalogs (src/core/i18n, src/products/<p>/messages).
  // shadcn components in src/components/ui stay as upstream and are not checked by this rule.
  {
    files: ["src/core/**/*.tsx", "src/products/**/*.tsx", "src/app/**/*.tsx"],
    rules: { "react/jsx-no-literals": ["error", { noStrings: false, ignoreProps: true }] },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "test-results/**",
    "playwright-report/**",
  ]),
]);

export default eslintConfig;
