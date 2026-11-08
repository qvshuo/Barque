import { Cell, Pie, PieChart } from "recharts";
import { money, type Dashboard } from "./api";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";

const colors = ["#718993", "#9a896d", "#83978b", "#af887e", "#92929d", "#b5ada0"];
const chartConfig = Object.fromEntries(
  colors.map((color, index) => [`segment${index}`, { color }]),
) satisfies ChartConfig;

export const OTHER_CATEGORIES = Symbol("other-categories");
export type CategoryFilter = string | typeof OTHER_CATEGORIES | null;
export function rankedCategories(groups: Dashboard["category_groups"]) {
  return groups
    .filter((group) => group.yearly_estimated_cny > 0)
    .sort((a, b) => b.yearly_estimated_cny - a.yearly_estimated_cny);
}

type CategoryGroup = Dashboard["category_groups"][number];

export function SpendingChart({
  groups,
  selected,
  onSelect,
}: {
  groups: CategoryGroup[];
  selected: CategoryFilter;
  onSelect: (category: CategoryFilter) => void;
}) {
  const ranked = rankedCategories(groups);
  const total = ranked.reduce((sum, group) => sum + group.yearly_estimated_cny, 0);
  if (!total) return null;
  const segments: { name: string; value: number; category: Exclude<CategoryFilter, null> }[] =
    ranked.slice(0, 5).map((group) => ({
      name: group.category_name,
      value: group.yearly_estimated_cny,
      category: group.category_name,
    }));
  if (ranked.length > 5)
    segments.push({
      name: "其他",
      value: ranked.slice(5).reduce((sum, group) => sum + group.yearly_estimated_cny, 0),
      category: OTHER_CATEGORIES,
    });
  const missingRates = groups.some((group) =>
    group.subscription_items.some((item) => item.amount_cny === null),
  );

  return (
    <section className="space-y-4 border-t px-4 pt-6 sm:px-6" aria-label="分类年支出">
      <h2 className="text-sm font-medium">分类年支出</h2>
      <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center sm:gap-10">
        <div className="relative w-48 shrink-0">
          <ChartContainer
            config={chartConfig}
            className="aspect-square w-full"
            aria-label="分类预计年支出环形图"
          >
            <PieChart accessibilityLayer>
              <Pie
                data={segments}
                dataKey="value"
                nameKey="name"
                innerRadius="68%"
                outerRadius="90%"
                stroke="none"
                isAnimationActive={false}
              >
                {segments.map((segment, index) => (
                  <Cell
                    key={index}
                    fill={`var(--color-segment${index})`}
                    className="cursor-pointer"
                    onClick={() =>
                      onSelect(selected === segment.category ? null : segment.category)
                    }
                  />
                ))}
              </Pie>
            </PieChart>
          </ChartContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
            <span className="text-xs text-muted-foreground">预计年支出</span>
            <span
              className="max-w-32 truncate text-lg font-semibold tabular-nums"
              title={money(total)}
            >
              {money(total, "CNY", true)}
            </span>
          </div>
        </div>
        <div className="w-full min-w-0 flex-1 space-y-1">
          {segments.map((segment, index) => {
            const content = (
              <>
                <span className="flex min-w-0 flex-1 items-center gap-3">
                  <span
                    className="size-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: colors[index] }}
                  />
                  <span className="min-w-0 truncate text-left" title={segment.name}>
                    {segment.name}
                  </span>
                </span>
                <span className="flex w-full min-w-0 items-start justify-between gap-3 pl-5.5 sm:w-auto sm:shrink-0 sm:pl-0">
                  <span className="min-w-0 wrap-anywhere text-left tabular-nums text-muted-foreground">
                    {money(segment.value)}
                  </span>
                  <span className="w-14 shrink-0 text-right tabular-nums text-muted-foreground">
                    {((segment.value / total) * 100).toFixed(1)}%
                  </span>
                </span>
              </>
            );
            return (
              <button
                key={index}
                type="button"
                onClick={() => onSelect(selected === segment.category ? null : segment.category)}
                aria-pressed={selected === segment.category}
                className="flex w-full flex-col items-stretch gap-1 rounded-md px-2 py-2 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-pressed:bg-accent sm:flex-row sm:items-center sm:gap-3"
              >
                {content}
              </button>
            );
          })}
          {missingRates && (
            <p className="px-2 pt-2 text-xs text-muted-foreground">
              部分外币汇率暂不可用，未计入统计
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
