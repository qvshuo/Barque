import { ArrowUp, ArrowDown, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

export type MoveActions = {
  canForward: boolean;
  canBackward: boolean;
  onMove: (direction: "forward" | "backward") => void;
};

export function MoveMenuItems({ canForward, canBackward, onMove, vertical = false }: MoveActions & { vertical?: boolean }) {
  return <>
    <DropdownMenuItem disabled={!canForward} onSelect={() => onMove("forward")}><ArrowUp />{vertical ? "上移" : "前移"}</DropdownMenuItem>
    <DropdownMenuItem disabled={!canBackward} onSelect={() => onMove("backward")}><ArrowDown />{vertical ? "下移" : "后移"}</DropdownMenuItem>
  </>;
}

export function CategoryMenu({ name, ...actions }: MoveActions & { name: string }) {
  return <DropdownMenu>
    <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${name} 分类操作`}><MoreHorizontal /></Button></DropdownMenuTrigger>
    <DropdownMenuContent align="end"><MoveMenuItems {...actions} vertical /></DropdownMenuContent>
  </DropdownMenu>;
}
