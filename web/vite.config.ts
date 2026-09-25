import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// Stage 0: build straight into a fixed output directory the Dockerfile
// copies into the image (`src/daysofcover/web_static/`, see ADR-004). The
// wheel published to PyPI does not include this directory before v1.0 --
// the Docker image and the static demo host are what ship it early.
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
