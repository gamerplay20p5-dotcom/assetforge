import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, parseBatchCsv, parseBatchJson, splitCsvLine, timeAgo } from "../src/lib";

describe("formatters", () => {
  it("formats bytes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(null)).toBe("—");
  });
  it("formats durations", () => {
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(125)).toBe("2m 05s");
    expect(formatDuration(null)).toBe("—");
  });
  it("formats relative time", () => {
    const now = Date.parse("2026-01-01T00:10:00Z");
    expect(timeAgo("2026-01-01T00:09:30Z", now)).toBe("30s atrás");
    expect(timeAgo(null)).toBe("nunca");
  });
});

describe("batch import", () => {
  it("splits quoted CSV cells", () => {
    expect(splitCsvLine('a,"b,c",d')).toEqual(["a", "b,c", "d"]);
  });
  it("expands count into sequential seeds", () => {
    const r = parseBatchCsv("name,category,seed,count\nCasa,house,100,3");
    expect(r.errors).toEqual([]);
    expect(r.items.map((i) => i.params.seed)).toEqual([100, 101, 102]);
    expect(r.items[0].name).toBe("Casa 001");
  });
  it("reports invalid numbers and missing names", () => {
    const r = parseBatchCsv("name,floors\n,3\nX,abc");
    expect(r.errors).toHaveLength(2);
    expect(r.items).toHaveLength(0);
  });
  it("parses JSON arrays and rejects bad input", () => {
    expect(parseBatchJson('[{"name":"A","params":{"category":"house"}}]').items).toHaveLength(1);
    expect(parseBatchJson("{").errors[0]).toMatch(/JSON inválido/);
    expect(parseBatchJson('[{"params":{}}]').errors).toHaveLength(1);
  });
});

import { checkImageFile, parseLods } from "../src/pages/AiGenerator";

describe("AI LOD ratios", () => {
  it("accepts descending values in [0.02, 1)", () => {
    expect(parseLods("0.5, 0.25 0.1")).toEqual([0.5, 0.25, 0.1]);
  });
  it("rejects ascending, out-of-range and NaN", () => {
    expect(parseLods("0.1, 0.5")).toBeNull();
    expect(parseLods("1.0")).toBeNull();
    expect(parseLods("0.01")).toBeNull();
    expect(parseLods("abc")).toBeNull();
  });
});

describe("checkImageFile", () => {
  it("aceita imagens de até 10 MB nos formatos permitidos", () => {
    expect(checkImageFile({ type: "image/png", size: 10 * 1024 * 1024 })).toBeNull();
    expect(checkImageFile({ type: "image/webp", size: 1000 })).toBeNull();
  });
  it("recusa acima de 10 MB e formatos não suportados", () => {
    expect(checkImageFile({ type: "image/png", size: 10 * 1024 * 1024 + 1 })).toMatch(/10 MB/);
    expect(checkImageFile({ type: "image/gif", size: 10 })).not.toBeNull();
  });
});
