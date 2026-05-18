import { getOnboardingSafetyNoteCopy } from "./onboardingSafetyNotice";

const assert = (condition: boolean, message: string) => {
  if (!condition) {
    throw new Error(message);
  }
};

const note = getOnboardingSafetyNoteCopy();

assert(note.bullets.length === 3, "safety note should keep three bullet points");
assert(note.bullets.every((line: string) => !line.includes("`r`n")), "bullet points should not contain literal rn markers");
assert(!note.boundaryNote.includes("`r`n"), "boundary note should not contain literal rn markers");
assert(note.boundaryNote.includes("不做诊断"), "boundary note should keep the non-diagnostic disclaimer");
