// Exact-path lifecycle operations. Only save_document may write a document.

function DocumentJSON(Value: String): String;
var
    I: Integer;
begin
    Result := '';
    for I := 1 to Length(Value) do
        if Ord(Value[I]) > 127 then Result := Result + '\u' + IntToHex(Ord(Value[I]), 4)
        else Result := Result + Value[I];
end;

function DocumentKindForPath(Path: String): String;
begin
    Result := '';
    case LowerCase(ExtractFileExt(Path)) of
        '.schdoc': Result := 'SCH';
        '.pcbdoc': Result := 'PCB';
        '.schlib': Result := 'SCHLIB';
        '.pcblib': Result := 'PCBLIB';
    end;
end;

function DocumentProject(Path: String): IProject;
var
    I, Matches: Integer;
    Candidate: IProject;
begin
    Result := nil;
    Matches := 0;
    for I := 0 to GetWorkspace.DM_ProjectCount - 1 do
    begin
        Candidate := GetWorkspace.DM_Projects(I);
        if NormalizedPath(Candidate.DM_ProjectFullPath) = NormalizedPath(Path) then
        begin
            Result := Candidate;
            Inc(Matches);
        end;
    end;
    if Matches <> 1 then Result := nil;
end;

function DocumentMembership(Project: IProject; Path: String): Integer;
var
    I: Integer;
begin
    Result := 0;
    for I := 0 to Project.DM_LogicalDocumentCount - 1 do
        if NormalizedPath(Project.DM_LogicalDocuments(I).DM_FullPath) = NormalizedPath(Path) then
            Inc(Result);
end;

function ManageDocument(Action, SpecPath: String): String;
var
    Spec, Props: TStringList;
    Doc: IServerDocument;
    Project: IProject;
    Path, Kind, ProjectPath, ErrorText: String;
    Started, Saved, WasModified, Changed, DryRun: Boolean;
    BeforeCount, AfterCount, I, Membership: Integer;
begin
    Result := 'ERROR: document spec file not found';
    if not FileExists(SpecPath) then Exit;
    Spec := TStringList.Create;
    Props := TStringList.Create;
    Started := False;
    Saved := False;
    Changed := False;
    WasModified := False;
    Doc := nil;
    Project := nil;
    ErrorText := '';
    BeforeCount := -1;
    AfterCount := -1;
    try
        Spec.LoadFromFile(SpecPath);
        Path := JSONUnescape(Spec.Values['document_path']);
        Kind := Spec.Values['document_kind'];
        ProjectPath := JSONUnescape(Spec.Values['project_path']);
        DryRun := Spec.Values['dry_run'] = '1';
        try
          repeat
            if (Kind = '') or (DocumentKindForPath(Path) <> Kind) then
                begin ErrorText := 'unsupported document kind or extension mismatch'; Break; end;
            if not DirectoryExists(ExtractFilePath(Path)) then
                begin ErrorText := 'parent directory does not exist'; Break; end;
            Doc := FindOpenDocument(Path);
            if Doc <> nil then
            begin
                if (NormalizedPath(Doc.FileName) <> NormalizedPath(Path)) or (UpperCase(Doc.Kind) <> Kind) then
                    begin ErrorText := 'open document identity does not match requested path and kind'; Break; end;
                WasModified := Doc.Modified;
            end;
            if Action = 'create_document' then
            begin
                if FileExists(Path) or (Doc <> nil) then
                    begin ErrorText := 'create_document refuses an existing file or open document'; Break; end;
                LogScriptError('create_document: new unsaved ' + Path);
                Started := True;
                Doc := Client.OpenNewDocument(Kind, '', Path, False);
                if Doc = nil then begin ErrorText := 'Altium did not create the document'; Break; end;
                Changed := True;
                Client.ShowDocument(Doc);
                if (NormalizedPath(Doc.FileName) <> NormalizedPath(Path)) or (UpperCase(Doc.Kind) <> Kind) then
                    begin ErrorText := 'created document identity mismatch; inspect open documents'; Break; end;
                if FileExists(Path) then begin ErrorText := 'creation unexpectedly wrote a file'; Break; end;
            end
            else if Action = 'save_document' then
            begin
                if Doc = nil then begin ErrorText := 'save_document requires the exact document to be open'; Break; end;
                if Pos('\\', Path) = 1 then begin ErrorText := 'network saves are unsupported'; Break; end;
                if Doc.BeingClosed then begin ErrorText := 'document is closing'; Break; end;
                if (Kind = 'SCH') or (Kind = 'SCHLIB') then
                    if SchServer.ProcessControl.ProcessDepth <> 0 then
                        begin ErrorText := 'schematic editor has an active transaction'; Break; end;
                if FileExists(Path) then
                    if (FileGetAttr(Path) and 1) <> 0 then begin ErrorText := 'target file is read-only'; Break; end;
                if not DryRun then
                begin
                    LogScriptError('save_document: save exact document ' + Path);
                    Started := True;
                    Saved := Doc.DoFileSave('');
                    if not Saved then begin ErrorText := 'Altium refused or cancelled saving'; Break; end;
                    if not FileExists(Path) then begin ErrorText := 'saved file is missing'; Break; end;
                    if Doc.Modified then begin ErrorText := 'document is still modified after save'; Break; end;
                    Changed := True;
                end;
            end
            else if Action = 'add_document_to_project' then
            begin
                if (LowerCase(ExtractFileExt(ProjectPath)) <> '.prjpcb') and
                   (LowerCase(ExtractFileExt(ProjectPath)) <> '.libpkg') then
                    begin ErrorText := 'target must be a PrjPcb or LibPkg'; Break; end;
                Project := DocumentProject(ProjectPath);
                if Project = nil then begin ErrorText := 'exact project must be open exactly once'; Break; end;
                if (Doc = nil) and not FileExists(Path) then
                    begin ErrorText := 'source must exist on disk or be an open named document'; Break; end;
                BeforeCount := Project.DM_LogicalDocumentCount;
                Membership := DocumentMembership(Project, Path);
                if Membership > 1 then begin ErrorText := 'source document membership is ambiguous'; Break; end;
                if Membership = 0 then
                begin
                    LogScriptError('add_document_to_project: add ' + Path + ' to ' + ProjectPath);
                    Started := True;
                    Project.DM_AddSourceDocument(Path);
                    Changed := True;
                end;
                AfterCount := Project.DM_LogicalDocumentCount;
                if DocumentMembership(Project, Path) <> 1 then
                    begin ErrorText := 'project membership readback failed'; Break; end;
            end
            else ErrorText := 'unknown document action';
          until True;
        except
            ErrorText := ExceptionMessage;
        end;
        AddJSONBoolean(Props, 'success', ErrorText = '');
        AddJSONProperty(Props, 'action', Action);
        AddJSONProperty(Props, 'document_path', Path);
        AddJSONProperty(Props, 'document_kind', Kind);
        AddJSONBoolean(Props, 'changed', Changed);
        AddJSONBoolean(Props, 'saved', Saved);
        AddJSONBoolean(Props, 'exists_on_disk', FileExists(Path));
        AddJSONBoolean(Props, 'may_have_partial_changes', (ErrorText <> '') and Started);
        AddJSONBoolean(Props, 'save_outcome_unknown', (ErrorText <> '') and Started and (Action = 'save_document') and not Saved);
        if Doc <> nil then
        begin
            AddJSONBoolean(Props, 'was_modified', WasModified);
            AddJSONBoolean(Props, 'is_modified', Doc.Modified);
        end;
        if Action = 'save_document' then AddJSONBoolean(Props, 'dry_run', DryRun);
        if Action = 'add_document_to_project' then
        begin
            AddJSONProperty(Props, 'project_path', ProjectPath);
            AddJSONBoolean(Props, 'project_saved', False);
            AddJSONInteger(Props, 'document_count_before', BeforeCount);
            AddJSONInteger(Props, 'document_count_after', AfterCount);
        end;
        if ErrorText <> '' then AddJSONProperty(Props, 'error', ErrorText);
        Result := DocumentJSON(BuildJSONObject(Props));
    finally
        Spec.Free;
        Props.Free;
    end;
end;

function ExecuteManageDocument(Action: String; Request: TStringList): String;
var
    I: Integer;
begin
    Result := 'ERROR: document spec_file is required';
    for I := 0 to Request.Count - 1 do
        if Pos('"spec_file":', Request[I]) > 0 then
        begin
            Result := ManageDocument(Action, JSONLineValue(Request[I]));
            Exit;
        end;
end;
