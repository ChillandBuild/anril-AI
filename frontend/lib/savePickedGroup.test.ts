import { beforeEach, describe, expect, it, vi } from "vitest";

const create = vi.fn();
const addMembers = vi.fn();
const remove = vi.fn();

vi.mock("@/lib/api", () => ({
  API_URL: "http://test",
  apiFetch: vi.fn(),
  getAuthHeaders: vi.fn(),
  api: { customerGroups: { create: (...a: unknown[]) => create(...a), addMembers: (...a: unknown[]) => addMembers(...a), remove: (...a: unknown[]) => remove(...a) } },
}));

import { savePickedPeopleAsGroup } from "./customersApi";

const NOW = new Date("2026-11-23T10:15:30Z");

describe("savePickedPeopleAsGroup", () => {
  beforeEach(() => {
    create.mockReset();
    addMembers.mockReset();
    remove.mockReset();
  });

  it("makes a picked group and adds each person once", async () => {
    create.mockResolvedValue({ id: "g1", name: "Picked · 23 Nov, 3:45 pm" });
    addMembers.mockResolvedValue({ added: 2 });
    const group = await savePickedPeopleAsGroup(["a", "b", "a"], NOW);
    expect(group.id).toBe("g1");
    expect(create).toHaveBeenCalledWith("Picked · 23 Nov, 3:45 pm"); // no rule: a fixed group
    expect(addMembers).toHaveBeenCalledWith("g1", ["a", "b"]);
  });

  it("sends the members in chunks of 1000", async () => {
    create.mockResolvedValue({ id: "g1", name: "x" });
    addMembers.mockResolvedValue({ added: 1 });
    await savePickedPeopleAsGroup(Array.from({ length: 2300 }, (_, i) => `id${i}`), NOW);
    expect(addMembers.mock.calls.map((c) => (c[1] as string[]).length)).toEqual([1000, 1000, 300]);
  });

  it("tries another name when the first is taken", async () => {
    create
      .mockRejectedValueOnce(new Error("A group with this name already exists"))
      .mockResolvedValueOnce({ id: "g2", name: "y" });
    addMembers.mockResolvedValue({ added: 1 });
    await savePickedPeopleAsGroup(["a"], NOW);
    expect(create).toHaveBeenNthCalledWith(2, "Picked · 23 Nov, 3:45:30 pm");
  });

  it("takes the empty group away when adding people fails, and says why", async () => {
    create.mockResolvedValue({ id: "g3", name: "z" });
    addMembers.mockRejectedValue(new Error("Permission required: leads.manage"));
    remove.mockResolvedValue(undefined);
    await expect(savePickedPeopleAsGroup(["a"], NOW)).rejects.toThrow("Permission required");
    expect(remove).toHaveBeenCalledWith("g3");
  });

  it("refuses nobody and does not call the server for other errors twice", async () => {
    await expect(savePickedPeopleAsGroup([], NOW)).rejects.toThrow("Pick at least one person");
    create.mockRejectedValue(new Error("Permission required: leads.manage"));
    await expect(savePickedPeopleAsGroup(["a"], NOW)).rejects.toThrow("Permission required");
    expect(create).toHaveBeenCalledTimes(1);
  });
});
