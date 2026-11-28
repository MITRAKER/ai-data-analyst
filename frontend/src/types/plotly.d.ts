// Types for the parts of Plotly that src/components/PlotlyChart.tsx uses.
// The package ships no types of its own.
declare module "plotly.js-cartesian-dist-min" {
  // Plain functions, not methods: they don't use `this`, so they can be
  // passed around, as the tests do with expect(Plotly.react).
  interface PlotlyApi {
    react: (
      root: HTMLElement,
      data: object[],
      layout: object,
      config: object,
    ) => Promise<HTMLElement>;
    purge: (root: HTMLElement) => void;
  }
  const Plotly: PlotlyApi;
  export default Plotly;
}
