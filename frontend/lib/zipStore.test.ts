import { describe, expect, it } from "vitest";
import { crc32, uniqueNames, zipStore } from "./zipStore";

describe("zipStore", () => {
  it("computes the standard CRC-32", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
  });

  it("makes repeated file names unique", () => {
    expect(uniqueNames(["a.png", "b.png", "a.png", "a.png"])).toEqual(["a.png", "b.png", "a (2).png", "a (3).png"]);
  });

  it("writes a zip with one entry per file and the end record", async () => {
    const blob = zipStore([
      { name: "a.png", data: new Uint8Array([1, 2, 3]) },
      { name: "b.png", data: new Uint8Array([4]) },
    ]);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const view = new DataView(bytes.buffer);
    expect(view.getUint32(0, true)).toBe(0x04034b50);
    const end = bytes.length - 22;
    expect(view.getUint32(end, true)).toBe(0x06054b50);
    expect(view.getUint16(end + 10, true)).toBe(2);
    expect(bytes.length).toBe(30 + 5 + 3 + 30 + 5 + 1 + 46 + 5 + 46 + 5 + 22);
  });
});
