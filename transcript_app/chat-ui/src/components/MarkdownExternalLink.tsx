import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { openExternalLink } from "@/lib/openExternal";

export function MarkdownExternalLink({
  href,
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & { href?: string }) {
  return (
    <a
      href={href}
      className="chat-external-link"
      {...rest}
      onClick={(e: MouseEvent<HTMLAnchorElement>) => {
        e.preventDefault();
        e.stopPropagation();
        if (href) void openExternalLink(href);
      }}
    >
      {children}
    </a>
  );
}
