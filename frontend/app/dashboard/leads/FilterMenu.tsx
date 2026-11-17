"use client";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface FilterMenuOption {
  value: string;
  label: string;
}

interface FilterMenuProps {
  label: string;
  options: FilterMenuOption[];
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  showValue?: boolean;
  dark?: boolean;
}

export interface FilterPopoverProps extends FilterMenuProps {
  trigger?: React.ReactNode;
}

export function FilterMenu({ label, options, value, onChange, showValue = true, dark = false }: FilterMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  const selectedLabel = options.find((o) => o.value === value)?.label || options[0]?.label;

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "shrink-0 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-bold flex items-center gap-1.5 transition-colors",
          dark
            ? "bg-white/10 text-white hover:bg-white/20"
            : "border border-[#e2e8f0] bg-white text-[#0A1528] hover:border-slate-300"
        )}
      >
        {showValue ? `${label}: ${selectedLabel}` : label}
        <ChevronDown size={14} />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 z-30 rounded-xl border border-[#e2e8f0] bg-white shadow-lg min-w-[180px]">
          {options.map((option) => (
            <button
              key={option.value}
              onClick={() => {
                onChange(option.value === value ? undefined : option.value);
                setOpen(false);
              }}
              className={cn(
                "w-full text-left px-4 py-2.5 text-xs font-semibold flex items-center justify-between hover:bg-slate-50 transition-colors",
                option.value === value ? "text-primary" : "text-[#334155]"
              )}
            >
              {option.label}
              {option.value === value && <Check size={14} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
