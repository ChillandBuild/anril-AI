/**
 * The New bill totals, the same maths as backend services/orders.compute_bill, so what the
 * screen shows is what gets saved. The discount is spread over the lines by value (the last
 * line takes the rounding) and each line's GST is on what was really charged. A simple bill
 * shows and adds no GST.
 */
export interface BillLineInput {
  unit_price_paise: number;
  qty: number;
  gst_rate: number | null;
}

export interface BillTotals {
  subtotal_paise: number;
  discount_paise: number;
  gst_paise: number;
  total_paise: number;
}

/** Python's round(): halves go to the even neighbour. */
function roundHalfEven(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (Math.abs(diff - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(x);
}

export function computeBill(lines: BillLineInput[], opts: { discount_paise: number; include_gst: boolean; bill_type: "gst" | "simple" }): BillTotals {
  const gross = lines.map((l) => Math.round(l.unit_price_paise) * l.qty);
  const subtotal = gross.reduce((a, b) => a + b, 0);
  const discount = Math.max(0, Math.min(Math.round(opts.discount_paise || 0), subtotal));
  let given = 0;
  let gst = 0;
  let total = 0;
  gross.forEach((g, i) => {
    const share = i === gross.length - 1 ? discount - given : subtotal ? Math.floor((discount * g) / subtotal) : 0;
    given += share;
    const charged = g - share;
    const rate = opts.bill_type === "gst" ? Number(lines[i].gst_rate || 0) : 0;
    let lineGst = 0;
    let lineTotal = charged;
    if (rate && opts.include_gst) {
      lineGst = roundHalfEven((charged * rate) / (100 + rate));
    } else if (rate) {
      lineGst = roundHalfEven((charged * rate) / 100);
      lineTotal = charged + lineGst;
    }
    gst += lineGst;
    total += lineTotal;
  });
  return { subtotal_paise: subtotal, discount_paise: discount, gst_paise: gst, total_paise: total };
}
