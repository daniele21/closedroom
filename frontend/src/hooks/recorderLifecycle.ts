export type RecorderLifecyclePhase =
  | 'idle'
  | 'preparing'
  | 'waiting_for_ai'
  | 'recording'
  | 'stopping';

export type RecorderLifecycleAction =
  | { type: 'prepare' }
  | { type: 'wait_for_ai' }
  | { type: 'resume_preparation' }
  | { type: 'recording_started' }
  | { type: 'stop_requested' }
  | { type: 'reset' };

export const INITIAL_RECORDER_LIFECYCLE: RecorderLifecyclePhase = 'idle';

export function recorderLifecycleReducer(
  state: RecorderLifecyclePhase,
  action: RecorderLifecycleAction,
): RecorderLifecyclePhase {
  switch (action.type) {
    case 'prepare':
      return state === 'idle' ? 'preparing' : state;
    case 'wait_for_ai':
      return state === 'preparing' ? 'waiting_for_ai' : state;
    case 'resume_preparation':
      return state === 'waiting_for_ai' ? 'preparing' : state;
    case 'recording_started':
      return state === 'preparing' || state === 'waiting_for_ai' ? 'recording' : state;
    case 'stop_requested':
      return state === 'recording' ? 'stopping' : state;
    case 'reset':
      return 'idle';
    default:
      return state;
  }
}

export function recorderLifecycleFlags(state: RecorderLifecyclePhase) {
  return {
    isRecording: state === 'recording' || state === 'stopping',
    isPreparingRecording: state === 'preparing' || state === 'waiting_for_ai',
    isWaitingForAi: state === 'waiting_for_ai',
  };
}
