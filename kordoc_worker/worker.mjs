import { readFile } from "node:fs/promises";
import { compare, parse, renderHwpxToSvg } from "kordoc";


async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (command === "compare" && args.length === 2) {
    const [oldBuffer, newBuffer] = await Promise.all(args.map((path) => readFile(path)));
    const result = await compare(oldBuffer, newBuffer);
    process.stdout.write(JSON.stringify({
      success: true,
      stats: result.stats ?? {},
      diffs: result.diffs ?? [],
    }));
    return;
  }

  if (command === "parse" && args.length === 1) {
    const result = await parse(await readFile(args[0]));
    if (!result.success) {
      throw new Error(result.error ?? "문서 파싱 실패");
    }
    process.stdout.write(JSON.stringify({
      success: true,
      fileType: result.fileType,
      markdown: result.markdown,
      blocks: result.blocks,
      warnings: result.warnings ?? [],
    }));
    return;
  }

  if (command === "render" && args.length === 1) {
    const result = await renderHwpxToSvg(await readFile(args[0]), { reflow: true });
    process.stdout.write(JSON.stringify({
      success: true,
      svg: result.svg,
      width: result.width,
      height: result.height,
      pageCount: result.pageCount,
      stats: result.stats ?? {},
      warnings: result.warnings ?? [],
    }));
    return;
  }

  throw new Error("사용법: worker.mjs compare <old> <new> | parse <file> | render <hwpx>");
}


main().catch((error) => {
  process.stderr.write(String(error?.message ?? error));
  process.exitCode = 1;
});
