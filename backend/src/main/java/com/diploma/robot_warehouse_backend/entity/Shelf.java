package com.diploma.robot_warehouse_backend.entity;

import com.diploma.robot_warehouse_backend.enums.Role;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.List;

@Entity
@Table(name = "shelves")
@Getter
@NoArgsConstructor
public class Shelf {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "shelf_id")
    private Integer id;

    @Column(name = "shelf_code", nullable = false, unique = true, length = 10)
    @Setter
    private String shelfCode;

    @Column(name = "map_x")
    private Double mapX;

    @Column(name = "role", nullable = false)
    @Enumerated(EnumType.STRING)
    @Setter
    private Role role;

    @Column(name = "map_y")
    private Double mapY;

    @Column(name = "map_yaw")
    private Double mapYaw;

    @Column(name = "description")
    @Setter
    private String description;

    @OneToMany(mappedBy = "shelf")
    private List<ShelfSlot> slots;

}
