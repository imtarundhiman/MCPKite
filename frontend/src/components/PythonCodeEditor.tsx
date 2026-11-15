import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";

import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import CodeMirror from "@uiw/react-codemirror";
import { EditorView } from "@codemirror/view";

export type PythonCodeEditorHandle = {
  focus: () => void;
};

type PythonCodeEditorProps = {
  id: string;
  labelId: string;
  helpId: string;
  errorId?: string;
  isInvalid?: boolean;
  source: string;
  onSourceChange: (source: string) => void;
  onBlur?: () => void;
};

const PythonCodeEditor = forwardRef<PythonCodeEditorHandle, PythonCodeEditorProps>(
  function PythonCodeEditor(
    {
      id,
      labelId,
      helpId,
      errorId,
      isInvalid = false,
      source,
      onSourceChange,
      onBlur,
    },
    ref,
  ) {
    const editorViewRef = useRef<EditorView | null>(null);
    const extensions = useMemo(
      () => [
        python(),
        oneDark,
        EditorView.contentAttributes.of({
          "aria-labelledby": labelId,
          "aria-describedby": errorId ? `${helpId} ${errorId}` : helpId,
          "aria-invalid": String(isInvalid),
          "aria-required": "true",
          spellcheck: "false",
        }),
      ],
      [errorId, helpId, isInvalid, labelId],
    );

    useImperativeHandle(
      ref,
      () => ({
        focus: () => editorViewRef.current?.focus(),
      }),
      [],
    );

    return (
      <CodeMirror
        id={id}
        className="code-editor"
        height="100%"
        extensions={extensions}
        basicSetup={{
          lineNumbers: true,
          highlightActiveLine: true,
          highlightActiveLineGutter: true,
          bracketMatching: true,
          closeBrackets: true,
          foldGutter: false,
        }}
        indentWithTab
        value={source}
        onChange={onSourceChange}
        onBlur={onBlur}
        onCreateEditor={(view) => {
          editorViewRef.current = view;
        }}
      />
    );
  },
);

export default PythonCodeEditor;
