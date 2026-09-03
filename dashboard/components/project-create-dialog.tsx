"use client";

import { useMemo, useState } from "react";
import { Plus, Send, Trash2, X } from "lucide-react";
import type { WorkspaceParticipant } from "../lib/types";
import { participantRoleLabels } from "../lib/ui/actor";

export type ProjectCreateValues = {
  name: string;
  roomNames: string[];
  inviteUserIds: string[];
};

type ProjectCreateDialogProps = {
  participants: WorkspaceParticipant[];
  submitting: boolean;
  error?: string;
  onClose: () => void;
  onSubmit: (values: ProjectCreateValues) => void;
};

export function ProjectCreateDialog({
  participants,
  submitting,
  error,
  onClose,
  onSubmit,
}: ProjectCreateDialogProps) {
  const [name, setName] = useState("");
  const [roomNames, setRoomNames] = useState([""]);
  const manager = useMemo(
    () => participants.find((participant) => participant.role === "manager"),
    [participants],
  );
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>(
    manager ? [manager.userId] : [],
  );
  const selectableParticipants = participants.filter((participant) => participant.role !== "manager");

  const updateRoomName = (index: number, value: string) => {
    setRoomNames((current) => current.map((roomName, roomIndex) => roomIndex === index ? value : roomName));
  };

  const toggleParticipant = (userId: string) => {
    setSelectedUserIds((current) => current.includes(userId)
      ? current.filter((selected) => selected !== userId)
      : [...current, userId]);
  };

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedRooms = roomNames.map((roomName) => roomName.trim()).filter(Boolean);
    if (!name.trim() || !trimmedRooms.length || submitting) {
      return;
    }
    onSubmit({
      name: name.trim(),
      roomNames: trimmedRooms,
      inviteUserIds: selectedUserIds,
    });
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !submitting) {
        onClose();
      }
    }}>
      <section className="project-dialog" role="dialog" aria-modal="true" aria-labelledby="project-dialog-title">
        <div className="dialog-header">
          <div>
            <p className="eyebrow">New project space</p>
            <h2 className="dialog-title" id="project-dialog-title">新建项目</h2>
            <p className="dialog-copy">创建真实 Matrix 房间，Manager 会话作为项目的主入口。</p>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} disabled={submitting} aria-label="关闭新建项目窗口">
            <X size={16} />
          </button>
        </div>

        <form className="project-form" onSubmit={submit}>
          <label className="form-field">
            <span className="form-label">项目名称</span>
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：材料核验"
              maxLength={120}
              disabled={submitting}
            />
          </label>

          <div className="form-field">
            <div className="form-label-row">
              <span className="form-label">项目房间</span>
              <span className="form-hint">至少一个</span>
            </div>
            <div className="room-name-list">
              {roomNames.map((roomName, index) => (
                <div className="room-name-row" key={`room-name-${index}`}>
                  <input
                    value={roomName}
                    onChange={(event) => updateRoomName(index, event.target.value)}
                    placeholder={index === 0 ? "主讨论" : "交付 / 复盘"}
                    maxLength={80}
                    disabled={submitting}
                    aria-label={`项目房间 ${index + 1}`}
                  />
                  <button
                    className="room-remove-button"
                    type="button"
                    onClick={() => setRoomNames((current) => current.filter((_value, roomIndex) => roomIndex !== index))}
                    disabled={submitting || roomNames.length === 1}
                    aria-label={`删除项目房间 ${index + 1}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
            <button className="add-room-button" type="button" onClick={() => setRoomNames((current) => [...current, ""])} disabled={submitting || roomNames.length >= 12}>
              <Plus size={13} /> 添加房间
            </button>
          </div>

          <fieldset className="form-field participant-field" disabled={submitting}>
            <legend className="form-label">邀请协作 Agent</legend>
            {manager ? (
              <label className="participant-option required">
                <input type="checkbox" checked disabled readOnly />
                <span className="participant-mark manager" />
                <span className="participant-copy">
                  <strong>{manager.displayName || manager.name}</strong>
                  <small>{participantRoleLabels.manager} · 必须邀请 · {manager.userId}</small>
                </span>
              </label>
            ) : (
              <p className="form-empty">当前 Controller 没有可用的 Manager，暂时无法创建项目。</p>
            )}
            {selectableParticipants.length > 0 && (
              <div className="participant-list">
                {selectableParticipants.map((participant) => (
                  <label className="participant-option" key={participant.userId}>
                    <input
                      type="checkbox"
                      checked={selectedUserIds.includes(participant.userId)}
                      onChange={() => toggleParticipant(participant.userId)}
                    />
                    <span className={`participant-mark ${participant.role}`} />
                    <span className="participant-copy">
                      <strong>{participant.displayName || participant.name}</strong>
                      <small>{participantRoleLabels[participant.role]} · {participant.userId}</small>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>

          {error && <p className="dialog-error">创建失败：{error}</p>}

          <div className="dialog-actions">
            <button className="dialog-secondary" type="button" onClick={onClose} disabled={submitting}>取消</button>
            <button className="dialog-primary" type="submit" disabled={submitting || !manager || !name.trim() || !roomNames.some((roomName) => roomName.trim())}>
              <Send size={13} />
              {submitting ? "正在创建真实房间…" : "创建项目"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
