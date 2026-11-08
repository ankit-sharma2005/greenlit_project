import type { ReactNode } from "react";

import "../../styles/charts.css";

export interface ChartFrameProps {
  /** Heading text, also the section's heading for screen readers. */
  title: string;
  /** One plain-language sentence about what is drawn and where it comes from. */
  description: string;
  /** The accessible name for the chart itself (`aria-label` on the SVG). */
  ariaLabel: string;
  /** Test hook for the whole chart; new testids only, never the page's. */
  testId: string;
  /** Data table columns, in the order they are shown. */
  columns: string[];
  /** Data table rows; the same numbers the SVG draws. */
  rows: string[][];
  /** The SVG. */
  children: ReactNode;
}

/**
 * The frame every run chart sits in: title, one-sentence description, the chart,
 * and a toggleable data table with the same numbers. The table is behind the toggle so
 * the graph stays the first thing a sighted reader sees; the declaration of how the data
 * was measured travels in the description, not only in the SVG.
 */
export function ChartFrame({
  title,
  description,
  ariaLabel,
  testId,
  columns,
  rows,
  children,
}: ChartFrameProps) {
  return (
    <section className="chart" data-testid={testId}>
      <div className="chart__head">
        <h3 className="chart__title">{title}</h3>
        <p className="chart__desc" id={`${testId}-desc`}>
          {description}
        </p>
      </div>
      <figure className="chart__figure" aria-label={ariaLabel}>
        {children}
      </figure>
      <details className="chart__data">
        <summary>Show data table</summary>
        <div className="chart__table-wrap">
          <table className="chart__table" data-testid={`${testId}-table`}>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${index}-${row.join("|")}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
