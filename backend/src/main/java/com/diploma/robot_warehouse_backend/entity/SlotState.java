package com.diploma.robot_warehouse_backend.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "slot_state")
@Getter
@NoArgsConstructor
public class SlotState {

    @Id
    @Column(name = "slot_id")
    private Integer id;

    @Column(nullable = false)
    @Setter
    private boolean occupied;

    @Column(name = "cube_qr")
    @Setter
    private String cubeQr;

    @Column(name = "updated_at", nullable = false)
    @Setter
    private LocalDateTime updatedAt;

    @Column(name = "robot_id")
    @Setter
    private String robotId;

    @Column(name = "reserved", nullable = false)
    @Setter
    private boolean reserved;

    @Column(name = "reserved_task_id")
    @Setter
    private Integer reservedTaskId;

    @OneToOne
    @MapsId
    @JoinColumn(name = "slot_id")
    @Setter
    private ShelfSlot slot;

    public SlotState(ShelfSlot slot) {
        this.slot = slot;
        this.occupied = false;
        this.reservedTaskId = null;
        this.cubeQr = null;
        this.reserved = false;
    }
}
