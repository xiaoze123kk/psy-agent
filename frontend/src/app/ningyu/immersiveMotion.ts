import { useReducedMotion, type Variants } from "framer-motion";

export const immersiveSpring = {
  type: "spring",
  damping: 25,
  stiffness: 300,
} as const;

export const immersiveExit = {
  duration: 0.2,
  ease: [0.4, 0, 1, 1],
} as const;

export function useNingyuReducedMotion() {
  return useReducedMotion();
}

export function buildFadeInUp(shouldReduceMotion: boolean): Variants {
  return shouldReduceMotion
    ? {
        initial: { opacity: 0 },
        animate: { opacity: 1 },
        exit: { opacity: 0 },
      }
    : {
        initial: { opacity: 0, y: 20 },
        animate: { opacity: 1, y: 0 },
        exit: { opacity: 0, y: -10 },
      };
}

export function buildScaleIn(shouldReduceMotion: boolean): Variants {
  return shouldReduceMotion
    ? {
        initial: { opacity: 0 },
        animate: { opacity: 1 },
        exit: { opacity: 0 },
      }
    : {
        initial: { opacity: 0, scale: 0.96 },
        animate: { opacity: 1, scale: 1 },
        exit: { opacity: 0, scale: 0.96 },
      };
}

export function buildSlideInX(shouldReduceMotion: boolean, direction: "left" | "right"): Variants {
  if (shouldReduceMotion) {
    return {
      initial: { opacity: 0 },
      animate: { opacity: 1 },
      exit: { opacity: 0 },
    };
  }

  const offset = direction === "left" ? -24 : 24;

  return {
    initial: { opacity: 0, x: offset },
    animate: { opacity: 1, x: 0 },
    exit: { opacity: 0, x: offset },
  };
}
