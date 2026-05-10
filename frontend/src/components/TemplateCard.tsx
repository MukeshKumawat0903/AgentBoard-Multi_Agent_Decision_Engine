/**
 * TemplateCard – compact card for a single debate template.
 *
 * Clicking a card fires onSelect with the template, which the parent
 * should use to pre-fill the DebateInput query field.
 */

import type { DebateTemplate } from "@/lib/types";

interface TemplateCardProps {
  template: DebateTemplate;
  onSelect: (template: DebateTemplate) => void;
}

const CATEGORY_COLORS: Record<string, string> = {
  Business:   "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300",
  Technology: "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300",
  Strategy:   "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300",
  Personal:   "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300",
  Finance:    "bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300",
};

export default function TemplateCard({ template, onSelect }: TemplateCardProps) {
  const badgeClass = CATEGORY_COLORS[template.category] ?? "bg-gray-100 text-gray-600";

  return (
    <button
      type="button"
      onClick={() => onSelect(template)}
      className="text-left w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4
                 hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-md
                 hover:-translate-y-0.5 transition-all duration-200 group"
    >
      <div className="flex items-start justify-between mb-2">
        <span className="text-2xl">{template.icon}</span>
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${badgeClass}`}>
          {template.category}
        </span>
      </div>
      <h4 className="font-semibold text-sm text-gray-800 dark:text-gray-200 mb-1 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition">
        {template.title}
      </h4>
      <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 leading-relaxed">
        {template.query}
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {template.tags.slice(0, 3).map((tag) => (
          <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
            {tag}
          </span>
        ))}
      </div>
    </button>
  );
}
