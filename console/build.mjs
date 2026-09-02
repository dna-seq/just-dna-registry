// Bundle console/src/*.ts into the one script the server ships. No minification: the Python test
// suite reads the bundle for the ROUTES table and the sibling-field names, and a reader debugging a
// live registry gets the source they can grep.
//
//   node build.mjs           write src/just_dna_registry/ui/static/app.js
//   node build.mjs --watch   rebuild on change
//   node build.mjs --check   exit 1 if the committed bundle is stale (what tests/test_ui.py runs)
import { build, context } from "esbuild";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const outfile = resolve(here, "../src/just_dna_registry/ui/static/app.js");
const options = {
  entryPoints: [resolve(here, "src/main.ts")],
  bundle: true,
  format: "iife",
  target: ["es2022"],
  platform: "browser",
  charset: "utf8",
  legalComments: "none",
  logLevel: "info",
  banner: { js: "/* Built from console/src by `npm run build` — edit the TypeScript, not this file. */" },
};

const mode = process.argv[2];
if (mode === "--watch") {
  const ctx = await context({ ...options, outfile });
  await ctx.watch();
} else if (mode === "--check") {
  const result = await build({ ...options, write: false, logLevel: "silent" });
  const fresh = result.outputFiles[0].text;
  const committed = readFileSync(outfile, "utf8");
  if (fresh !== committed) {
    console.error(`stale bundle: ${outfile} does not match console/src — run \`npm run build\``);
    process.exit(1);
  }
} else {
  await build({ ...options, outfile });
}
