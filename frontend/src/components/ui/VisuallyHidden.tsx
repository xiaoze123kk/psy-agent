import type { ReactNode } from "react";

import "./VisuallyHidden.css";

type VisuallyHiddenProps = {
  children: ReactNode;
};

export function VisuallyHidden({ children }: VisuallyHiddenProps) {
  return <span className="ui-visually-hidden">{children}</span>;
}
