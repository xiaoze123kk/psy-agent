import "./Spinner.css";

type SpinnerProps = {
  label?: string;
  size?: "sm" | "md";
};

export function Spinner({ label = "加载中", size = "md" }: SpinnerProps) {
  return (
    <span className="ui-spinner" role="status" aria-label={label} data-size={size}>
      <span className="ui-spinner__ring" aria-hidden="true" />
    </span>
  );
}
