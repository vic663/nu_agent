import { useEffect } from "react";
import { useLocation } from "react-router-dom";

// Scroll to the top of the page whenever the route changes (React Router keeps the scroll
// position of the previous page otherwise). "instant" is required: index.css sets
// `html { scroll-behavior: smooth }` for the hero's Learn More button, and the plain
// scrollTo(0, 0) form inherits that, so the new page would visibly slide up from the old offset.
export default function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [pathname]);
  return null;
}
