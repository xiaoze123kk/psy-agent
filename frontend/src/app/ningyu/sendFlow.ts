export type SendConversationState = { kind: "thread"; threadId: string } | { kind: "draft" } | null;

export function shouldCreateThreadForSend(activeConversation: SendConversationState): boolean {
  return activeConversation?.kind !== "thread";
}
