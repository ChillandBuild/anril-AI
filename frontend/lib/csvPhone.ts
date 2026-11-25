/** Phone numbers in a CSV: Excel turns +919659950974 into 9.19660E+11. Writing the cell as the
 *  formula ="+919659950974" makes Excel and Google Sheets show the full text. Only plain numbers
 *  get this; anything else is left for the writer's normal formula-safe handling. */
const PLAIN_PHONE = /^\+?\d[\d \-()]{3,24}$/;
const PHONE_FORMULA = /^="\+?\d[\d \-()]{3,24}"$/;

/** The raw cell text, before CSV quoting (the writer then quotes it, because it holds a `"`). */
export function phoneCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value).trim();
  if (!text) return "";
  return PLAIN_PHONE.test(text) ? `="${text}"` : String(value);
}

/** True for a cell phoneCell produced, so a writer's formula guard (which prefixes ' to cells
 *  starting with =) can let it through untouched. */
export function isPhoneFormula(cell: string): boolean {
  return PHONE_FORMULA.test(cell);
}
