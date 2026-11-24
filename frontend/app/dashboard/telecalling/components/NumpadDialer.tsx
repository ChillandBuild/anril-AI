"use client";
import React from "react";
import { Phone, Delete } from "lucide-react";

interface NumpadDialerProps {
  value: string;
  onChange: (val: string) => void;
  onDial: () => void;
  dialing: boolean;
  disabled?: boolean;
}

export default function NumpadDialer({ value, onChange, onDial, dialing, disabled = false }: NumpadDialerProps) {
  const buttons = [
    { digit: "1", sub: "" },
    { digit: "2", sub: "ABC" },
    { digit: "3", sub: "DEF" },
    { digit: "4", sub: "GHI" },
    { digit: "5", sub: "JKL" },
    { digit: "6", sub: "MNO" },
    { digit: "7", sub: "PQRS" },
    { digit: "8", sub: "TUV" },
    { digit: "9", sub: "WXYZ" },
    { digit: "*", sub: "" },
    { digit: "0", sub: "+" },
    { digit: "#", sub: "" },
  ];

  const handleDigitClick = (digit: string) => {
    onChange(value + digit);
  };

  const handleBackspace = () => {
    onChange(value.slice(0, -1));
  };

  return (
    <div className="w-full max-w-[280px] mx-auto bg-white border border-[#e2e8f0]/80 rounded-3xl p-4 shadow-sm flex flex-col gap-3">
      <div className="flex items-center gap-1 bg-[#f8fafc] border border-[#e2e8f0]/80 rounded-2xl px-3 py-2.5">
        <input
          type="text"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Enter a number or a name"
          aria-label="Number or name"
          className="flex-1 bg-transparent font-body text-base font-bold text-[#13284A] text-center tracking-wider outline-none"
        />
        {value.length > 0 && (
          <button
            onClick={handleBackspace}
            disabled={disabled}
            className="text-[#94a3b8] hover:text-[#334155] transition-colors p-1"
          >
            <Delete size={16} />
          </button>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2">
        {buttons.map((btn) => (
          <button
            key={btn.digit}
            onClick={() => handleDigitClick(btn.digit)}
            disabled={disabled}
            className="flex flex-col items-center justify-center bg-[#f8fafc] border border-[#e2e8f0]/60 hover:bg-[var(--primary-50)] hover:border-[var(--primary-100)] hover:text-[var(--primary-800)] active:scale-95 rounded-2xl py-2.5 transition-all disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-[#f8fafc] disabled:hover:text-inherit"
          >
            <span className="font-display text-base font-extrabold text-[#13284A] hover:text-inherit">{btn.digit}</span>
            <span className="font-label text-[7.5px] text-[#94a3b8] font-bold tracking-wider uppercase mt-0.5">{btn.sub || "\u00A0"}</span>
          </button>
        ))}

        <button
          onClick={onDial}
          disabled={disabled || dialing || !value.trim() || /[a-z]/i.test(value)}
          className="col-span-3 mt-1 py-3.5 bg-primary hover:bg-primary-dark text-white rounded-2xl flex items-center justify-center gap-2 font-display text-sm font-extrabold shadow-[0_4px_12px_rgba(var(--primary-500-rgb),0.25)] hover:shadow-[0_6px_16px_rgba(var(--primary-500-rgb),0.4)] disabled:opacity-50 transition-all hover:scale-[1.01] active:scale-[0.99]"
        >
          <Phone size={14} className="fill-white" />
          {dialing ? "Dialing..." : "Call Now"}
        </button>
      </div>
    </div>
  );
}
