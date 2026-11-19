"use client";

import {useTransition} from "react";
import {RefreshCw} from "lucide-react";
import {Button} from "./button";
import {Spinner} from "./spinner";

export function RetryButton({retry,label="Reload",disabled,...props}:Omit<React.ComponentProps<typeof Button>,"onClick"|"children">&{retry:()=>void|Promise<void>;label?:string}){
  const [pending,startTransition]=useTransition();
  return <Button aria-label={label} {...props} type="button" disabled={disabled||pending} aria-busy={pending} onClick={()=>startTransition(async()=>{await retry();})}>
    {pending?<Spinner aria-label="Reloading" data-icon="inline-start"/>:<RefreshCw aria-hidden="true" data-icon="inline-start"/>}
    {label}
  </Button>;
}
