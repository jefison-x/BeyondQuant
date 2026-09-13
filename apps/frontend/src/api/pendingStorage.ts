/** Storage mechanics only. Domain modules own namespaces, validation and recovery. */
export function readPendingText(key:string,maxCharacters:number,tooLargeMessage:string):string|null {
  const raw=localStorage.getItem(key);
  if(raw!==null && raw.length>maxCharacters) throw Error(tooLargeMessage);
  return raw;
}
export function writePendingText(key:string,raw:string,maxCharacters:number,tooLargeMessage:string):void {
  if(raw.length>maxCharacters) throw Error(tooLargeMessage);
  // Failure must propagate before the caller sends its domain mutation.
  localStorage.setItem(key,raw);
}
