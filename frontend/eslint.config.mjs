// ESLint checks the web UI's code. It runs in CI with --max-warnings=0, so
// every finding must be fixed. docs/CODING_STANDARD.md explains how these rules
// map to NASA/JPL's "Power of Ten" rules.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import tseslint from "typescript-eslint";

export default defineConfig([
  // Next.js's own rules, including React, React hooks and accessibility.
  ...nextVitals,
  ...nextTs,
  // typescript-eslint's strictest rule sets. They use the type checker, so they
  // can see, for example, a promise that nobody waits for.
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  {
    rules: {
      // Rule 1: simple control flow.
      complexity: ["error", 10],
      "max-depth": ["error", 3],
      "max-nested-callbacks": ["error", 3],
      "no-labels": "error",
      // Rule 2: every loop has a fixed upper bound. Loop with `for ... of` over
      // something of fixed size, or count up to a limit.
      "no-restricted-syntax": [
        "error",
        { selector: "WhileStatement", message: "R2: use a for loop with a fixed bound." },
        { selector: "DoWhileStatement", message: "R2: use a for loop with a fixed bound." },
        { selector: "ForStatement[test=null]", message: "R2: a for loop needs a condition." },
        { selector: "ForInStatement", message: "Use for...of over Object.entries()." },
      ],
      "no-constant-condition": ["error", { checkLoops: "all" }],
      // Rule 4: short functions (60 lines, like the Python code) with few parameters.
      "max-lines-per-function": [
        "error",
        { max: 60, skipBlankLines: true, skipComments: true, IIFEs: true },
      ],
      "max-params": ["error", 4],
      // Rule 6: the smallest possible scope.
      "no-var": "error",
      "prefer-const": "error",
      "@typescript-eslint/no-shadow": "error",
      // Rule 7: check every return value. (strictTypeChecked already reports
      // promises that are not awaited, and errors thrown that are not Errors.)
      "no-empty": ["error", { allowEmptyCatch: false }],
      // Rule 8: no metaprogramming. No eval, no new Function(), no HTML strings.
      "no-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "react/no-danger": "error",
      // Check data with code, never with `as`: a cast only silences the checker.
      "@typescript-eslint/consistent-type-assertions": ["error", { assertionStyle: "never" }],
      // A parameter whose name starts with "_" is there only for its type, as
      // in a fake fetch() whose calls a test reads back.
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    // Tests may be longer, and may use test helpers that take functions.
    files: ["**/*.test.ts", "**/*.test.tsx", "src/test/**", "e2e/**"],
    rules: {
      "max-lines-per-function": "off",
      "max-nested-callbacks": "off",
    },
  },
  {
    // Config files are plain JavaScript, outside the TypeScript project.
    files: ["**/*.mjs"],
    extends: [tseslint.configs.disableTypeChecked],
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "coverage/**",
    "playwright-report/**",
    "test-results/**",
    "next-env.d.ts",
  ]),
]);
