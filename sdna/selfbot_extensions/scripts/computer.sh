#!/bin/bash
# Computer Control Helper Script
# Usage: computer.sh <command> [args...]

source ~/.display_env 2>/dev/null || {
    export DISPLAY=:99
    export WIDTH=1920
    export HEIGHT=1080
}

CMD="$1"
shift

case "$CMD" in
    screenshot|ss|s)
        PATH_OUT="${1:-/tmp/screen.png}"
        import -window root "$PATH_OUT" && echo "Screenshot saved: $PATH_OUT"
        ;;

    click|c)
        X="$1"; Y="$2"
        if [ -n "$X" ] && [ -n "$Y" ]; then
            xdotool mousemove "$X" "$Y" click 1
            echo "Clicked at ($X, $Y)"
        else
            xdotool click 1
            echo "Clicked at current position"
        fi
        ;;

    rightclick|rc)
        X="$1"; Y="$2"
        if [ -n "$X" ] && [ -n "$Y" ]; then
            xdotool mousemove "$X" "$Y" click 3
        else
            xdotool click 3
        fi
        echo "Right-clicked"
        ;;

    doubleclick|dc)
        X="$1"; Y="$2"
        if [ -n "$X" ] && [ -n "$Y" ]; then
            xdotool mousemove "$X" "$Y" click --repeat 2 --delay 100 1
        else
            xdotool click --repeat 2 --delay 100 1
        fi
        echo "Double-clicked"
        ;;

    move|m)
        X="$1"; Y="$2"
        xdotool mousemove "$X" "$Y"
        echo "Moved to ($X, $Y)"
        ;;

    type|t)
        TEXT="$*"
        xdotool type --delay 12 -- "$TEXT"
        echo "Typed: $TEXT"
        ;;

    key|k)
        KEY="$1"
        xdotool key -- "$KEY"
        echo "Pressed: $KEY"
        ;;

    drag|d)
        X1="$1"; Y1="$2"; X2="$3"; Y2="$4"
        xdotool mousemove "$X1" "$Y1" mousedown 1 mousemove "$X2" "$Y2" mouseup 1
        echo "Dragged from ($X1,$Y1) to ($X2,$Y2)"
        ;;

    getmouse|gm)
        xdotool getmouselocation --shell
        ;;

    getwindow|gw)
        xdotool getactivewindow getwindowname
        ;;

    focuswindow|fw)
        WNAME="$1"
        xdotool search --name "$WNAME" windowactivate
        echo "Focused window: $WNAME"
        ;;

    wait|w)
        SECS="${1:-1}"
        sleep "$SECS"
        echo "Waited ${SECS}s"
        ;;

    *)
        echo "Computer Control Helper"
        echo ""
        echo "Commands:"
        echo "  screenshot [path]      Take screenshot (default: /tmp/screen.png)"
        echo "  click [X Y]            Left click (at coords or current pos)"
        echo "  rightclick [X Y]       Right click"
        echo "  doubleclick [X Y]      Double click"
        echo "  move X Y               Move mouse"
        echo "  type TEXT              Type text"
        echo "  key KEYNAME            Press key (Return, ctrl+c, alt+Tab)"
        echo "  drag X1 Y1 X2 Y2       Drag between coordinates"
        echo "  getmouse               Get mouse position"
        echo "  getwindow              Get active window name"
        echo "  focuswindow NAME       Focus window by name"
        echo "  wait [SECS]            Wait (default 1s)"
        ;;
esac
