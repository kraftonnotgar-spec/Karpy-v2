import * as React from "react";
import {Button} from "@/components/ui/button";
import {cn} from "@/lib/utils";

type AttachmentState="idle"|"uploading"|"processing"|"error"|"done";

function Attachment({className,state="done",...props}:React.ComponentProps<"div">&{state?:AttachmentState}){
  return <div data-slot="attachment" data-state={state} className={cn(
    "group/attachment flex min-w-0 items-center gap-3 rounded-lg border bg-card p-3 text-card-foreground focus-within:ring-2 focus-within:ring-ring/50 data-[state=idle]:border-dashed data-[state=error]:border-destructive",
    className,
  )} {...props}/>;
}

function AttachmentMedia({className,variant="icon",...props}:React.ComponentProps<"div">&{variant?:"icon"|"image"}){
  return <div data-slot="attachment-media" data-variant={variant} className={cn(
    "flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted text-muted-foreground [&>svg]:size-5 [&>img]:size-full [&>img]:object-cover group-data-[state=error]/attachment:bg-destructive/10 group-data-[state=error]/attachment:text-destructive",
    className,
  )} {...props}/>;
}

function AttachmentContent({className,...props}:React.ComponentProps<"div">){
  return <div data-slot="attachment-content" className={cn("min-w-0 flex-1 space-y-1",className)} {...props}/>;
}

function AttachmentTitle({className,...props}:React.ComponentProps<"span">){
  return <span data-slot="attachment-title" className={cn("block truncate text-sm font-medium",className)} {...props}/>;
}

function AttachmentDescription({className,...props}:React.ComponentProps<"span">){
  return <span data-slot="attachment-description" className={cn("block break-words text-xs text-muted-foreground group-data-[state=error]/attachment:text-destructive",className)} {...props}/>;
}

function AttachmentActions({className,...props}:React.ComponentProps<"div">){
  return <div data-slot="attachment-actions" className={cn("flex shrink-0 items-center gap-0.5",className)} {...props}/>;
}

function AttachmentAction({type="button",variant="ghost",size="icon-sm",...props}:React.ComponentProps<typeof Button>){
  return <Button data-slot="attachment-action" type={type} variant={variant} size={size} {...props}/>;
}

export {Attachment,AttachmentMedia,AttachmentContent,AttachmentTitle,AttachmentDescription,AttachmentActions,AttachmentAction};
