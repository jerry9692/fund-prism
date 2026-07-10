/**
 * BrandMark — Fund Prism 品牌 Logo
 *
 * 使用 public/logo.png 作为 Logo 图片（蓝色棱镜 + 彩虹光谱 + K线图）。
 * 顶栏显示图片，favicon 复用同一张 PNG。
 */

interface BrandMarkProps {
  size?: number;
  className?: string;
}

const LOGO_SRC = "/logo.png";

export function BrandMark({ size = 32, className }: BrandMarkProps) {
  return (
    <img
      src={LOGO_SRC}
      alt="Fund Prism"
      width={size}
      height={size}
      className={className}
      style={{
        display: "block",
        flexShrink: 0,
        objectFit: "contain",
      }}
    />
  );
}

/** 注入浏览器 favicon（直接使用 PNG） */
export function injectFavicon() {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/png";
    document.head.appendChild(link);
  } else {
    link.type = "image/png";
  }
  link.href = LOGO_SRC;
}
