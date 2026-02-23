package com.diploma.robot_warehouse_backend.entity;

import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Entity
@Table(name = "shelf_slots")
@Getter
@NoArgsConstructor
public class ShelfSlot {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "slot_id")
    private Integer id;

    @Column(nullable = false)
    @Enumerated(EnumType.STRING)
    private Side side;

    @Column(nullable = false)
    @Enumerated(EnumType.STRING)
    private Level level;

    @Column(name = "apriltag_id")
    private Integer apriltagId;

    @Column(nullable = false)
    @Setter
    private boolean enabled;

    @OneToOne(mappedBy = "slot")
    private SlotState state;

    @ManyToOne(optional = false, fetch = FetchType.LAZY)
    @JoinColumn(name = "shelf_code", referencedColumnName = "shelf_code", nullable = false)
    private Shelf shelf;
}
