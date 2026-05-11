import { OnboardingGuide } from "./OnboardingGuide";

export function DebugOnboardingGuide({ onBack }: { onBack: () => void }) {
  return <OnboardingGuide onBack={onBack} onComplete={onBack} completeLabel="调试完成" />;
}
