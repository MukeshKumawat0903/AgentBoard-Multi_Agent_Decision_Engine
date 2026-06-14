/**
 * Button – shared button primitive with variants, sizes and a loading state.
 *
 * Variants:
 *   primary   – solid accent, one per view
 *   secondary – neutral filled
 *   outline   – bordered, transparent background
 *   ghost     – borderless, low-emphasis
 *   danger    – destructive solid red
 */

"use client";

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-accent-600 text-white hover:bg-accent-700 shadow-sm",
  secondary:
    "bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700",
  outline:
    "border border-line-strong text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800",
  ghost:
    "text-gray-500 hover:text-gray-800 hover:bg-gray-100 dark:text-gray-400 dark:hover:text-gray-100 dark:hover:bg-gray-800",
  danger:
    "bg-red-600 text-white hover:bg-red-700 shadow-sm",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "text-xs px-3 py-1.5 gap-1.5",
  md: "text-sm px-4 py-2.5 gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  children: ReactNode;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, disabled, className = "", children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center font-medium rounded-lg transition
                  active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500
                  ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
      {...rest}
    >
      {loading && <Loader2 className={size === "sm" ? "w-3 h-3 animate-spin" : "w-4 h-4 animate-spin"} aria-hidden="true" />}
      {children}
    </button>
  );
});

export default Button;
